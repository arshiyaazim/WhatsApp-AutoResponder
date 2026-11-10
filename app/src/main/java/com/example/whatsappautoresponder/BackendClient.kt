package com.example.whatsappautoresponder

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.URL
import javax.net.ssl.HttpsURLConnection

object BackendClient {
    private const val TAG = "WAResponderAI"

    fun generateReply(
        baseUrl: String,
        accessToken: String,
        message: String,
        knowledge: List<KnowledgeEntry>,
        history: JSONArray
    ): String? {
        val base = baseUrl.trim().trimEnd('/')
        if (!base.startsWith("https://", ignoreCase = true) || accessToken.isBlank()) return null
        var connection: HttpsURLConnection? = null
        return try {
            val conn = (URL("$base/v1/reply").openConnection() as HttpsURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 35_000
                doOutput = true
                instanceFollowRedirects = false
                setRequestProperty("Authorization", "Bearer $accessToken")
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Accept", "application/json")
            }
            connection = conn
            val entries = JSONArray().apply {
                knowledge.take(30).forEach { entry ->
                    put(JSONObject()
                        .put("question", entry.question)
                        .put("answer", entry.answer)
                        .put("keywords", entry.keywords))
                }
            }
            val payload = JSONObject()
                .put("message", message.take(4000))
                .put("knowledge", entries)
                .put("history", history)
            conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val status = conn.responseCode
            if (status !in 200..299) {
                conn.errorStream?.close()
                Log.w(TAG, "AI backend returned HTTP $status")
                null
            } else {
                val response = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                JSONObject(response).optString("reply").trim().takeIf { it.isNotBlank() }?.take(2000)
            }
        } catch (e: Exception) {
            Log.w(TAG, "AI backend request failed (${e.javaClass.simpleName})")
            null
        } finally {
            connection?.disconnect()
        }
    }
}
