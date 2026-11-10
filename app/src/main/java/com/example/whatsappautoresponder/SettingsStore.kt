package com.example.whatsappautoresponder

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

data class KnowledgeEntry(val question: String, val answer: String, val keywords: String = "")
data class ContactRule(val identifier: String, val allow: Boolean)

data class AppSettings(
    val autoReplyEnabled: Boolean = false,
    val selectedPackages: Set<String> = emptySet(),
    val allowlistOnly: Boolean = false,
    val rules: List<ContactRule> = emptyList(),
    val knowledge: List<KnowledgeEntry> = emptyList(),
    val generativeAiEnabled: Boolean = false,
    val aiBackendUrl: String = "",
    val aiBackendToken: String = "",
    // Retained for a future supported integration. The notification API cannot execute call actions.
    val callAutomationEnabled: Boolean = false,
    val callAction: String = "observe"
)

object SettingsStore {
    private const val PREFS = "wa_auto_responder"
    private const val KEY = "settings_v1"

    fun load(context: Context): AppSettings {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
            ?: return AppSettings()
        return try {
            val root = JSONObject(raw)
            val packages = root.optJSONArray("packages").toStringList().toSet()
            val rulesArray = root.optJSONArray("rules") ?: JSONArray()
            val rules = (0 until rulesArray.length()).mapNotNull { i ->
                rulesArray.optJSONObject(i)?.let {
                    ContactRule(it.optString("identifier"), it.optBoolean("allow"))
                }
            }.filter { it.identifier.isNotBlank() }
            val entriesArray = root.optJSONArray("knowledge") ?: JSONArray()
            val entries = (0 until entriesArray.length()).mapNotNull { i ->
                entriesArray.optJSONObject(i)?.let {
                    KnowledgeEntry(it.optString("question"), it.optString("answer"), it.optString("keywords"))
                }
            }.filter { it.question.isNotBlank() && it.answer.isNotBlank() }
            AppSettings(
                autoReplyEnabled = root.optBoolean("autoReplyEnabled", false),
                selectedPackages = packages,
                allowlistOnly = root.optBoolean("allowlistOnly", false),
                rules = rules,
                knowledge = entries,
                generativeAiEnabled = root.optBoolean("generativeAiEnabled", false),
                aiBackendUrl = root.optString("aiBackendUrl", ""),
                aiBackendToken = root.optString("aiBackendToken", ""),
                callAutomationEnabled = root.optBoolean("callAutomationEnabled", false),
                callAction = root.optString("callAction", "observe")
            )
        } catch (_: Exception) {
            AppSettings()
        }
    }

    fun save(context: Context, settings: AppSettings) {
        val root = JSONObject()
            .put("autoReplyEnabled", settings.autoReplyEnabled)
            .put("packages", JSONArray(settings.selectedPackages.toList()))
            .put("allowlistOnly", settings.allowlistOnly)
            .put("rules", JSONArray().apply {
                settings.rules.forEach { put(JSONObject().put("identifier", it.identifier).put("allow", it.allow)) }
            })
            .put("knowledge", JSONArray().apply {
                settings.knowledge.forEach {
                    put(JSONObject().put("question", it.question).put("answer", it.answer).put("keywords", it.keywords))
                }
            })
            .put("generativeAiEnabled", settings.generativeAiEnabled)
            .put("aiBackendUrl", settings.aiBackendUrl)
            .put("aiBackendToken", settings.aiBackendToken)
            .put("callAutomationEnabled", settings.callAutomationEnabled)
            .put("callAction", settings.callAction)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, root.toString()).apply()
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        return (0 until length()).mapNotNull { optString(it, null) }
    }
}

/** Contact rule matching is intentionally exact: it avoids replying to a similarly named person. */
object ContactPolicy {
    fun shouldReply(settings: AppSettings, notificationIdentity: String): Boolean {
        val identity = normalize(notificationIdentity)
        if (identity.isBlank()) return !settings.allowlistOnly
        val matched = settings.rules.filter { normalize(it.identifier) == identity }
        if (matched.any { !it.allow }) return false // deny always wins, even if duplicate rules exist
        if (matched.any { it.allow }) return true
        return !settings.allowlistOnly
    }

    private fun normalize(value: String): String {
        val trimmed = value.trim().lowercase(Locale.ROOT)
        val digits = trimmed.filter(Char::isDigit)
        return if (digits.length >= 7) digits else trimmed.replace(Regex("\\s+"), " ")
    }
}

/** Local knowledge retrieval (TF-IDF cosine similarity). This retrieves a curated answer; it is not a generative LLM. */
object KnowledgeMatcher {
    private val tokenPattern = Regex("[\\p{L}\\p{N}]+", RegexOption.IGNORE_CASE)

    fun answer(query: String, entries: List<KnowledgeEntry>, minimumScore: Double = 0.12): String? {
        val best = ranked(query, entries).firstOrNull() ?: return null
        return if (best.second >= minimumScore) best.first.answer else null
    }

    fun topEntries(query: String, entries: List<KnowledgeEntry>, limit: Int = 10): List<KnowledgeEntry> =
        ranked(query, entries).take(limit.coerceAtLeast(0)).map { it.first }

    private fun ranked(query: String, entries: List<KnowledgeEntry>): List<Pair<KnowledgeEntry, Double>> {
        if (query.isBlank() || entries.isEmpty()) return emptyList()
        val docs = entries.map { tokenize("${it.question} ${it.keywords}") }
        val queryTerms = tokenize(query)
        if (queryTerms.isEmpty()) return emptyList()
        val vocabulary = (docs.flatten() + queryTerms).toSet()
        val documentFrequency = vocabulary.associateWith { term -> docs.count { term in it } }
        fun vector(tokens: List<String>): Map<String, Double> {
            val counts = tokens.groupingBy { it }.eachCount()
            return counts.mapValues { (term, count) ->
                val idf = kotlin.math.ln(1.0 + (docs.size + 1.0) / (1.0 + (documentFrequency[term] ?: 0)))
                count * idf
            }
        }
        val queryVector = vector(queryTerms)
        val queryNorm = kotlin.math.sqrt(queryVector.values.sumOf { it * it })
        if (queryNorm == 0.0) return emptyList()
        return entries.indices.map { index ->
            val docVector = vector(docs[index])
            val docNorm = kotlin.math.sqrt(docVector.values.sumOf { it * it })
            val dot = queryVector.entries.sumOf { (term, weight) -> weight * (docVector[term] ?: 0.0) }
            entries[index] to if (docNorm == 0.0) 0.0 else dot / (queryNorm * docNorm)
        }.sortedByDescending { it.second }
    }

    private fun tokenize(text: String): List<String> = tokenPattern.findAll(text.lowercase(Locale.ROOT)).map { it.value }.toList()
}
