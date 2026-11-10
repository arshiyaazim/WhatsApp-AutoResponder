package com.example.whatsappautoresponder

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** Stores a small local per-contact history; raw contact identifiers are never sent to the backend. */
object ConversationStore {
    private const val PREFS = "wa_local_conversations"
    private const val ROOT_KEY = "threads_v1"
    private const val MAX_TURNS = 8
    private const val MAX_THREADS = 100

    fun threadId(packageName: String, identity: String): String {
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest("$packageName|${identity.trim().lowercase()}".toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    @Synchronized
    fun recentHistory(context: Context, threadId: String): JSONArray {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val root = readRoot(prefs.getString(ROOT_KEY, null))
        val thread = root.optJSONObject(threadId) ?: JSONObject()
        val history = thread.optJSONArray("turns") ?: JSONArray()
        thread.put("turns", history).put("updatedAt", System.currentTimeMillis())
        root.put(threadId, thread)
        prune(root)
        prefs.edit().putString(ROOT_KEY, root.toString()).apply()
        return JSONArray(history.toString())
    }

    @Synchronized
    fun appendExchange(context: Context, threadId: String, incoming: String, reply: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val root = readRoot(prefs.getString(ROOT_KEY, null))
        val thread = root.optJSONObject(threadId) ?: JSONObject()
        val turns = thread.optJSONArray("turns") ?: JSONArray()
        turns.put(JSONObject().put("role", "user").put("content", incoming.take(2000)))
        turns.put(JSONObject().put("role", "assistant").put("content", reply.take(2000)))
        while (turns.length() > MAX_TURNS) turns.remove(0)
        thread.put("turns", turns).put("updatedAt", System.currentTimeMillis())
        root.put(threadId, thread)
        prune(root)
        prefs.edit().putString(ROOT_KEY, root.toString()).apply()
    }

    private fun readRoot(raw: String?): JSONObject = try { JSONObject(raw ?: "{}") } catch (_: Exception) { JSONObject() }

    private fun prune(root: JSONObject) {
        if (root.length() <= MAX_THREADS) return
        val oldest = (0 until root.length()).mapNotNull { i ->
            val key = root.names()?.optString(i) ?: return@mapNotNull null
            key to (root.optJSONObject(key)?.optLong("updatedAt") ?: 0L)
        }.sortedBy { it.second }
        oldest.take(root.length() - MAX_THREADS).forEach { root.remove(it.first) }
    }
}
