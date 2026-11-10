package com.example.whatsappautoresponder

import android.content.Context
import android.net.Uri
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.URL
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

object BackendClient {
    private const val TAG = "WAResponderAI"
    private const val MAX_IMAGE_BYTES = 8 * 1024 * 1024
    private val allowedImageMimes = setOf("image/jpeg", "image/png", "image/webp", "application/pdf")

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
                    put(JSONObject().put("question", entry.question).put("answer", entry.answer).put("keywords", entry.keywords))
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

    /** Uploads only the URI explicitly selected by the user; bytes are kept in memory and not cached. */
    fun uploadImage(
        context: Context,
        baseUrl: String,
        accessToken: String,
        uri: Uri,
        task: String,
        question: String,
        knowledge: List<KnowledgeEntry>
    ): JSONObject {
        require(task == "extract-image" || task == "understand-image") { "Unsupported image task" }
        require(baseUrl.startsWith("https://", ignoreCase = true) && accessToken.isNotBlank()) { "HTTPS backend URL and token are required" }
        val mime = context.contentResolver.getType(uri)?.substringBefore(';')?.lowercase()
            ?: throw IllegalArgumentException("Selected file type could not be identified")
        require(mime in allowedImageMimes) { "Choose a JPEG, PNG, WEBP image or PDF" }
        val bytes = context.contentResolver.openInputStream(uri)?.use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var total = 0
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                total += count
                require(total <= MAX_IMAGE_BYTES) { "File is larger than 8 MB" }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        } ?: throw IllegalArgumentException("Selected file could not be opened")
        require(bytes.isNotEmpty()) { "Selected file is empty" }

        val boundary = "WAForm-${UUID.randomUUID()}"
        val base = baseUrl.trim().trimEnd('/')
        var connection: HttpsURLConnection? = null
        return try {
            val conn = (URL("$base/api/ai/$task").openConnection() as HttpsURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 60_000
                doOutput = true
                instanceFollowRedirects = false
                setRequestProperty("Authorization", "Bearer $accessToken")
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setRequestProperty("Accept", "application/json")
            }
            connection = conn
            conn.outputStream.use { raw ->
                val out = raw.buffered()
                fun field(name: String, value: String) {
                    out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray(Charsets.UTF_8))
                    out.write(value.toByteArray(Charsets.UTF_8))
                    out.write("\r\n".toByteArray(Charsets.UTF_8))
                }
                out.write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"user-selected-attachment\"\r\nContent-Type: $mime\r\n\r\n".toByteArray(Charsets.UTF_8))
                out.write(bytes)
                out.write("\r\n".toByteArray(Charsets.UTF_8))
                if (task == "understand-image") {
                    field("question", question.take(4000))
                    val entries = JSONArray().apply {
                        knowledge.take(30).forEach { put(JSONObject().put("question", it.question).put("answer", it.answer).put("keywords", it.keywords)) }
                    }
                    field("knowledge_json", entries.toString())
                    field("history_json", "[]")
                }
                out.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
                out.flush()
            }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                Log.w(TAG, "Image backend returned HTTP $status")
                throw IllegalStateException("Backend returned HTTP $status")
            }
            JSONObject(body)
        } catch (e: Exception) {
            Log.w(TAG, "Image backend request failed (${e.javaClass.simpleName})")
            throw e
        } finally {
            connection?.disconnect()
        }
    }
}
