from __future__ import annotations

import time
import uuid
from typing import Any

from .config import TASKS, custom_provider_defaults, default_fallback_orders, default_provider_configs, env_credentials
from .fallback_manager import FallbackManager
from .health_monitor import HealthMonitor
from .key_manager import KeyManager
from .monitoring.usage_tracker import BudgetExceeded, UsageTracker
from .providers.base import ProviderAdapter
from .providers.registry import create_adapter
from .quota_manager import QuotaManager
from .security.secret_manager import SecretManager
from .storage import GatewayStore
from .tasks.prompts import TEXT_INSTRUCTIONS, build_text_prompt
from .types import GatewayResult, KeyCredential, ProviderConfig, ProviderError, ProviderResult, Task


class GatewayUnavailable(Exception):
    def __init__(self, category: str, message: str, request_id: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.category, self.message, self.request_id, self.status_code = category, message, request_id, status_code


class GatewayManager:
    # Bound one logical request even if an administrator configures many duplicate keys/providers.
    MAX_KEY_ATTEMPTS_PER_PROVIDER = 3
    MAX_PROVIDER_KEY_ATTEMPTS_PER_REQUEST = 24

    def __init__(self, database_path: str | None = None) -> None:
        self.secrets = SecretManager()
        self.store = GatewayStore(self.secrets, database_path)
        custom_providers = custom_provider_defaults()
        providers = default_provider_configs() + custom_providers
        orders = default_fallback_orders([provider.provider_id for provider in custom_providers])
        for task in TASKS:
            orders.setdefault(task, [])
        self.store.initialize(providers, orders)
        self.keys = KeyManager(self.store)
        self.health = HealthMonitor(self.store)
        self.quotas = QuotaManager(self.store, self.health)
        self.fallback = FallbackManager(self.store)
        self.usage = UsageTracker(self.store)

    def _budget_check(self, request_id: str) -> None:
        try:
            self.usage.check_budget(request_id)
        except BudgetExceeded as exc:
            raise GatewayUnavailable(exc.category, exc.message, request_id, exc.status_code) from None
        except Exception:
            raise GatewayUnavailable("budget_store_unavailable", "AI budget protection is unavailable", request_id, 503) from None

    def _record(self, *, request_id: str, task: Task, provider_id: str | None, model: str | None,
                key: KeyCredential | None, outcome: str, started: float, result: ProviderResult | None,
                category: str | None, fallback_count: int) -> None:
        self.usage.record(request_id=request_id, task=task, provider_id=provider_id, model=model,
                          key=key, outcome=outcome, started=started, result=result,
                          category=category, fallback_count=fallback_count)

    def _attempt(self, task: Task, message: str, knowledge: list[dict[str, Any]], history: list[dict[str, str]],
                 mime_type: str | None, image: bytes | None, question: str) -> GatewayResult:
        request_id = uuid.uuid4().hex
        try:
            self.usage.check_budget(request_id)
        except BudgetExceeded as exc:
            raise GatewayUnavailable(exc.category, exc.message, request_id, exc.status_code) from None
        except Exception:
            # Database/reservation failures fail closed; never call a provider without a reservation.
            raise GatewayUnavailable("budget_store_unavailable", "AI budget protection is unavailable", request_id, 503) from None
        budget_state = {"uncertain": False}
        try:
            return self._run_attempt(request_id, task, message, knowledge, history, mime_type, image, question, budget_state)
        finally:
            try:
                self.usage.finish_budget(request_id, uncertain=budget_state["uncertain"])
            except Exception:
                # Reservation lease expiry conservatively retains the full allowance.
                pass

    def _run_attempt(self, request_id: str, task: Task, message: str, knowledge: list[dict[str, Any]],
                     history: list[dict[str, str]], mime_type: str | None, image: bytes | None,
                     question: str, budget_state: dict[str, bool]) -> GatewayResult:
        automatic_failover = self.fallback.enabled()
        attempted = 0
        last_category = "no_provider_available"
        providers = {p.provider_id: p for p in self.store.providers()}

        for provider_id in self.fallback.order_for(task):
            if provider_id == "local-tfidf":
                local_started = time.perf_counter()
                local = self.fallback.local_tfidf_answer(message, knowledge)
                if local:
                    self._record(request_id=request_id, task=task, provider_id="local-tfidf", model="local-tfidf",
                                 key=None, outcome="success", started=local_started, result=None,
                                 category=None, fallback_count=attempted)
                    return GatewayResult(local, "local-tfidf", "local-tfidf", request_id, attempted)
                last_category = "no_local_match"
                continue

            config = providers.get(provider_id)
            if not config or not config.enabled:
                continue
            adapter = create_adapter(config.provider_type)
            model = config.models.get(task, "").strip()
            if not adapter or not model or not adapter.supports(task, mime_type):
                continue
            if self.health.is_cooling(provider_id):
                last_category = "provider_cooldown"
                if not automatic_failover:
                    raise GatewayUnavailable(last_category, "Selected provider is cooling down", request_id, 503)
                continue
            try:
                credentials = self.keys.eligible_for(config)
            except RuntimeError:
                raise GatewayUnavailable("secret_configuration", "Encrypted provider keys cannot be loaded; check server secret configuration", request_id, 503) from None
            if not credentials:
                last_category = "no_eligible_keys"
                if not automatic_failover:
                    raise GatewayUnavailable(last_category, "Selected provider has no eligible API keys", request_id, 503)
                continue

            skipped_projects: set[str] = set()
            skip_provider = False
            provider_attempts = 0
            for credential in credentials:
                if attempted >= self.MAX_PROVIDER_KEY_ATTEMPTS_PER_REQUEST:
                    break
                if provider_attempts >= self.MAX_KEY_ATTEMPTS_PER_PROVIDER:
                    break
                if credential.project_id and credential.project_id in skipped_projects:
                    continue
                attempted += 1
                provider_attempts += 1
                started = time.perf_counter()
                provider_returned = False
                try:
                    result = self._invoke(adapter, task, config, credential, model, message, knowledge, history,
                                          mime_type, image, question)
                    provider_returned = True
                    if not result.text.strip():
                        raise ProviderError("empty_response", "Provider returned an empty response", retryable=True)
                    self.health.record_success(provider_id, credential.key_id)
                    self._record(request_id=request_id, task=task, provider_id=provider_id, model=result.model,
                                 key=credential, outcome="success", started=started, result=result,
                                 category=None, fallback_count=attempted - 1)
                    return GatewayResult(result.text, provider_id, result.model, request_id, attempted - 1,
                                         result.input_tokens, result.output_tokens, credential.key_id, credential.project_id)
                except Exception as error:
                    normalized = error if isinstance(error, ProviderError) else adapter.normalize_error(error)
                    if provider_returned or normalized.category not in {"authentication", "permission", "invalid_request"}:
                        # Persist uncertainty before failure logging; if SQLite is transiently unavailable,
                        # the request-local flag still makes finalization retain the reservation.
                        budget_state["uncertain"] = True
                        try:
                            self.store.mark_budget_uncertain(request_id)
                        except Exception:
                            pass
                    last_category = normalized.category
                    action = self.quotas.record_failure(provider_id, credential, normalized)
                    if action == "skip_project" and credential.project_id:
                        skipped_projects.add(credential.project_id)
                    if action == "skip_provider":
                        skip_provider = True
                    self._record(request_id=request_id, task=task, provider_id=provider_id, model=model,
                                 key=credential, outcome="error", started=started, result=None,
                                 category=normalized.category, fallback_count=attempted - 1)
                    if not automatic_failover:
                        raise GatewayUnavailable(last_category, "Selected AI provider request failed", request_id, 502)
                    if skip_provider:
                        break
            if not automatic_failover:
                raise GatewayUnavailable(last_category, "Selected AI provider request failed", request_id, 502)

        raise GatewayUnavailable(last_category, "No configured provider could process this request", request_id, 503)

    @staticmethod
    def _invoke(adapter: ProviderAdapter, task: Task, config: ProviderConfig, credential: KeyCredential,
                model: str, message: str, knowledge: list[dict[str, Any]], history: list[dict[str, str]],
                mime_type: str | None, image: bytes | None, question: str) -> ProviderResult:
        if task == "text_generation":
            return adapter.generate_text(api_key=credential.secret, model=model, instructions=TEXT_INSTRUCTIONS,
                                         prompt=build_text_prompt(message, knowledge, history), history=history,
                                         base_url=config.base_url)
        if image is None or mime_type is None:
            raise ProviderError("invalid_request", "Image data is missing")
        if task == "image_extraction":
            return adapter.extract_text_from_image(api_key=credential.secret, model=model, image=image,
                                                   mime_type=mime_type, base_url=config.base_url)
        if task == "image_understanding":
            return adapter.understand_image(api_key=credential.secret, model=model, image=image,
                                            mime_type=mime_type, question=question, knowledge=knowledge,
                                            history=history, base_url=config.base_url)
        raise ProviderError("unsupported_task", "Unsupported AI task")

    def generate_text(self, message: str, knowledge: list[dict[str, Any]], history: list[dict[str, str]]) -> GatewayResult:
        return self._attempt("text_generation", message, knowledge, history, None, None, "")

    def process_image(self, task: Task, image: bytes, mime_type: str, question: str = "",
                      knowledge: list[dict[str, Any]] | None = None,
                      history: list[dict[str, str]] | None = None) -> GatewayResult:
        if task not in {"image_extraction", "image_understanding"}:
            raise GatewayUnavailable("invalid_task", "Unsupported image task", uuid.uuid4().hex, 400)
        return self._attempt(task, question, knowledge or [], history or [], mime_type, image, question)

    def _all_credentials(self, provider: ProviderConfig) -> list[KeyCredential]:
        return self.keys.all_for(provider)

    @staticmethod
    def _capabilities(provider: ProviderConfig) -> list[str]:
        adapter = create_adapter(provider.provider_type)
        if not adapter:
            return []
        return [task for task, model in provider.models.items() if model and
                (task == "text_generation" or adapter.supports(task, "image/jpeg"))]

    def providers_public(self) -> list[dict[str, Any]]:
        health = self.store.provider_health()
        result = []
        for provider in self.store.providers():
            try:
                count = len(self._all_credentials(provider))
            except RuntimeError:
                count = 0
            default_health = {"status": "available" if count and provider.enabled else "not_configured"}
            result.append({"id": provider.provider_id, "type": provider.provider_type, "name": provider.name,
                           "enabled": provider.enabled, "models": provider.models,
                           "capabilities": self._capabilities(provider), "configured_key_count": count,
                           "health": health.get(provider.provider_id, default_health)})
        return result

    def admin_providers(self) -> list[dict[str, Any]]:
        key_health = self.store.key_health()
        project_health = self.store.project_health()
        result = []
        for provider in self.store.providers():
            key_rows = self.store.all_key_metadata(provider.provider_id)
            env_rows = []
            for key in env_credentials(provider.provider_id, provider.provider_type):
                state = key_health.get(key.key_id, {"status": "available"})
                if key.project_id and (provider.provider_id, key.project_id) in project_health:
                    state = {**state, **project_health[(provider.provider_id, key.project_id)]}
                env_rows.append({"id": key.key_id, "source": "environment", "project_id": key.project_id,
                                 "label": "environment key", "enabled": True, **state})
            for row in key_rows:
                row["source"] = "database_encrypted"
                row["enabled"] = bool(row["enabled"])
                row.update(key_health.get(row["id"], {"status": "available"}))
                project_id = row.get("project_id")
                if project_id and (provider.provider_id, project_id) in project_health:
                    row.update(project_health[(provider.provider_id, project_id)])
            result.append({"id": provider.provider_id, "type": provider.provider_type, "name": provider.name,
                           "enabled": provider.enabled, "models": provider.models, "base_url": provider.base_url,
                           "keys": env_rows + key_rows})
        return result

    def status(self) -> dict[str, Any]:
        settings = self.store.get_settings()
        return {"providers": self.providers_public(), "fallback_order": self.store.fallback_orders(),
                "automatic_failover": settings.get("automatic_failover", True),
                "daily_limits": {"max_requests": settings.get("max_requests_per_day"),
                                 "max_estimated_spend_usd": settings.get("max_daily_spend_usd"),
                                 "max_request_spend_reservation_usd": settings.get("max_request_spend_usd")},
                "requests_per_minute_limit": settings.get("max_requests_per_minute"),
                "today": self.store.daily_usage()}

    def test_provider(self, provider_id: str) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        self._budget_check(request_id)
        budget_state = {"uncertain": False}
        try:
            return self._test_provider_reserved(provider_id, request_id, budget_state)
        finally:
            try:
                self.usage.finish_budget(request_id, uncertain=budget_state["uncertain"])
            except Exception:
                pass

    def _test_provider_reserved(self, provider_id: str, request_id: str,
                                budget_state: dict[str, bool]) -> dict[str, Any]:
        provider = self.store.get_provider(provider_id)
        if not provider or not provider.enabled:
            raise GatewayUnavailable("provider_disabled", "Provider is missing or disabled", request_id, 404)
        adapter = create_adapter(provider.provider_type)
        model = provider.models.get("text_generation", "")
        if not adapter or not model:
            raise GatewayUnavailable("unsupported_provider", "Provider has no configured text model", request_id, 400)
        try:
            credentials = self.keys.eligible_for(provider)
        except RuntimeError:
            raise GatewayUnavailable("secret_configuration", "Provider key encryption configuration is unavailable", request_id, 503) from None
        if not credentials:
            raise GatewayUnavailable("no_eligible_keys", "No eligible API keys configured", request_id, 503)
        errors = []
        skipped_projects: set[str] = set()
        for credential in credentials:
            if len(errors) >= self.MAX_KEY_ATTEMPTS_PER_PROVIDER:
                break
            if credential.project_id and credential.project_id in skipped_projects:
                continue
            started = time.perf_counter()
            provider_returned = False
            try:
                adapter.health_check(api_key=credential.secret, model=model, base_url=provider.base_url)
                provider_returned = True
                self.health.record_success(provider_id, credential.key_id)
                self._record(request_id=request_id, task="text_generation", provider_id=provider_id, model=model,
                             key=credential, outcome="success", started=started, result=None,
                             category=None, fallback_count=0)
                return {"request_id": request_id, "provider_id": provider_id, "model": model,
                        "key_id": credential.key_id, "latency_ms": int((time.perf_counter() - started) * 1000), "healthy": True}
            except Exception as exc:
                normalized = exc if isinstance(exc, ProviderError) else adapter.normalize_error(exc)
                if provider_returned or normalized.category not in {"authentication", "permission", "invalid_request"}:
                    budget_state["uncertain"] = True
                    try:
                        self.store.mark_budget_uncertain(request_id)
                    except Exception:
                        pass
                errors.append(normalized.category)
                action = self.quotas.record_failure(provider_id, credential, normalized)
                self._record(request_id=request_id, task="text_generation", provider_id=provider_id, model=model,
                             key=credential, outcome="error", started=started, result=None,
                             category=normalized.category, fallback_count=len(errors) - 1)
                if action == "skip_project" and credential.project_id:
                    skipped_projects.add(credential.project_id)
                if action == "skip_provider":
                    break
        raise GatewayUnavailable(errors[-1] if errors else "provider_error", "Provider connectivity test failed", request_id, 502)

    def reset_project(self, provider_id: str, project_id: str) -> bool:
        return self.store.reset_project(provider_id, project_id)

    def pricing_status(self) -> dict[str, Any]:
        return self.usage.pricing_status()
