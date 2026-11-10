package com.example.whatsappautoresponder

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.os.Bundle
import java.security.MessageDigest

class WhatsAppNotificationService : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val settings = SettingsStore.load(this)
        if (!settings.autoReplyEnabled || sbn.packageName !in settings.selectedPackages) return
        if (sbn.notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (sbn.notification.category == Notification.CATEGORY_CALL) return

        val extras = sbn.notification.extras ?: return
        val title = (extras.getCharSequence(Notification.EXTRA_TITLE)
            ?: extras.getCharSequence(Notification.EXTRA_TITLE_BIG))?.toString()?.trim().orEmpty()
        val body = (extras.getCharSequence(Notification.EXTRA_TEXT)
            ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT))?.toString()?.trim().orEmpty()
        if (body.isBlank()) return

        val (identity, message) = identifyAndExtract(title, body)
        if (message.isBlank() || !ContactPolicy.shouldReply(settings, identity)) return
        val response = KnowledgeMatcher.answer(message, settings.knowledge) ?: return
        if (alreadyHandled(sbn, message)) return

        val replyAction = sbn.notification.actions
            ?.firstOrNull { action -> action.remoteInputs?.any { it.allowFreeFormInput } == true }
            ?: return
        val remoteInput = replyAction.remoteInputs?.firstOrNull { it.allowFreeFormInput } ?: return
        try {
            val fillIn = android.content.Intent()
            val results = Bundle().apply { putCharSequence(remoteInput.resultKey, response) }
            RemoteInput.addResultsToIntent(arrayOf(remoteInput), fillIn, results)
            replyAction.actionIntent.send(this, 0, fillIn)
        } catch (_: PendingIntent.CanceledException) {
            // The WhatsApp notification may have expired before the reply action was sent.
        } catch (_: SecurityException) {
            // Android / WhatsApp can reject a reply action; no attempt is made to bypass it.
        }
    }

    private fun identifyAndExtract(title: String, body: String): Pair<String, String> {
        val generic = title.equals("WhatsApp", true) || title.equals("WhatsApp Business", true)
        if (generic) {
            val separator = body.indexOf(": ")
            if (separator in 1..80) return body.substring(0, separator).trim() to body.substring(separator + 2).trim()
        }
        return title to body
    }

    private fun alreadyHandled(sbn: StatusBarNotification, message: String): Boolean {
        val source = "${sbn.packageName}|${sbn.tag}|${sbn.id}|${message}"
        val digest = MessageDigest.getInstance("SHA-256").digest(source.toByteArray()).joinToString("") { "%02x".format(it) }
        val prefs = getSharedPreferences("wa_reply_dedupe", MODE_PRIVATE)
        val key = "sent_$digest"
        val now = System.currentTimeMillis()
        val last = prefs.getLong(key, 0L)
        if (now - last < 10 * 60 * 1000L) return true
        prefs.edit().putLong(key, now).apply()
        return false
    }
}
