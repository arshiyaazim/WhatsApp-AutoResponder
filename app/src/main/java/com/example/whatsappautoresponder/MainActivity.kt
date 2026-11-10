package com.example.whatsappautoresponder

import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var root: LinearLayout
    private var settings = AppSettings()
    private var editKnowledgeIndex: Int? = null
    private var editRuleIndex: Int? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = SettingsStore.load(this)
        render()
    }

    override fun onResume() {
        super.onResume()
        if (::root.isInitialized) render()
    }

    private fun render() {
        val scroll = ScrollView(this)
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(20), dp(20), dp(32))
            setBackgroundColor(0xFFF7F8F6.toInt())
        }
        scroll.addView(root)
        setContentView(scroll)

        text("WA Auto Responder", 25f, true)
        text("Android companion · এই ফোনেই সেটিংস সংরক্ষিত থাকবে", 14f)
        space(12)
        val status = if (isNotificationAccessEnabled()) "নোটিফিকেশন অ্যাক্সেস: চালু" else "নোটিফিকেশন অ্যাক্সেস: বন্ধ"
        text(status, 15f, true)
        button("নোটিফিকেশন অ্যাক্সেস সেট করুন") {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        section("১. অটো-রিপ্লে")
        toggle("অটো-রিপ্লে চালু", settings.autoReplyEnabled) { checked ->
            updateSettings(settings.copy(autoReplyEnabled = checked))
        }
        text("শুধু নিচে নির্বাচিত WhatsApp অ্যাপের নতুন নোটিফিকেশন থেকে, Android-এর inline reply সুবিধা পাওয়া গেলে উত্তর পাঠানো হবে।", 13f)

        section("কোন WhatsApp ইনস্টলেশন")
        text("এখানে অ্যাপ-প্যাকেজ বাছাই করা যায়; একই WhatsApp অ্যাপের ভিতরের আলাদা অ্যাকাউন্ট আলাদাভাবে শনাক্ত করার নিশ্চয়তা Android দেয় না।", 13f)
        val packages = listOf(
            "com.whatsapp" to "WhatsApp",
            "com.whatsapp.w4b" to "WhatsApp Business"
        )
        packages.forEach { (pkg, label) ->
            val installed = try { packageManager.getPackageInfo(pkg, 0); true } catch (_: Exception) { false }
            val check = CheckBox(this).apply {
                text = if (installed) label else "$label (ইনস্টল নেই)"
                isChecked = pkg in settings.selectedPackages
                isEnabled = installed
                setOnCheckedChangeListener { _, checked ->
                    val updated = settings.selectedPackages.toMutableSet().apply {
                        if (checked) add(pkg) else remove(pkg)
                    }
                    updateSettings(settings.copy(selectedPackages = updated))
                }
            }
            root.addView(check)
        }

        section("২. কার কাছ থেকে উত্তর দেবেন")
        toggle("Allowlist mode — তালিকায় Allow থাকা ব্যক্তিদেরই উত্তর দিন", settings.allowlistOnly) { checked ->
            updateSettings(settings.copy(allowlistOnly = checked))
        }
        text("নোটিফিকেশনে যে নাম/নম্বর দেখা যায় সেটিই সঠিকভাবে লিখুন। নম্বর দেখা না গেলে নাম দিয়ে মিলবে। Deny নিয়ম সবসময় অগ্রাধিকার পাবে।", 13f)
        val identifier = input("ফোন নম্বর বা নোটিফিকেশনের নাম")
        val typeGroup = RadioGroup(this).apply { orientation = RadioGroup.HORIZONTAL }
        val allowRadio = RadioButton(this).apply { text = "Allow"; id = View.generateViewId(); isChecked = true }
        val denyRadio = RadioButton(this).apply { text = "Deny"; id = View.generateViewId() }
        typeGroup.addView(allowRadio)
        typeGroup.addView(denyRadio)
        root.addView(typeGroup)
        button("নিয়ম সেভ (যোগ/পরিবর্তন)") {
            val value = identifier.text.toString().trim()
            if (value.isBlank()) toast("নাম বা নম্বর লিখুন") else {
                val rule = ContactRule(value, allowRadio.isChecked)
                val newRules = settings.rules.toMutableList()
                val at = editRuleIndex
                if (at == null) {
                    newRules.removeAll { it.identifier.equals(value, true) }
                    newRules.add(rule)
                } else if (at in newRules.indices) {
                    newRules[at] = rule
                }
                editRuleIndex = null
                identifier.setText("")
                updateSettings(settings.copy(rules = newRules))
            }
        }
        if (settings.rules.isEmpty()) text("এখনও কোনো contact rule নেই।", 13f)
        settings.rules.forEachIndexed { index, rule ->
            val line = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            line.addView(TextView(this).apply {
                text = "${if (rule.allow) "ALLOW" else "DENY"}  ·  ${rule.identifier}"
                textSize = 14f
            }, LinearLayout.LayoutParams(0, -2, 1f))
            line.addView(Button(this).apply {
                text = "Edit"
                setOnClickListener {
                    editRuleIndex = index
                    identifier.setText(rule.identifier)
                    (if (rule.allow) allowRadio else denyRadio).isChecked = true
                    scrollToTop()
                }
            })
            line.addView(Button(this).apply {
                text = "Delete"
                setOnClickListener {
                    editRuleIndex = null
                    updateSettings(settings.copy(rules = settings.rules.filterIndexed { i, _ -> i != index }))
                }
            })
            root.addView(line)
        }

        section("৩. Knowledge base")
        text("প্রশ্ন/বিষয় ও নির্দিষ্ট উত্তর যোগ করুন। অ্যাপ স্থানীয় TF‑IDF মিল দিয়ে সেরা উত্তর বেছে নেয়—এটি নিজে থেকে নতুন বাক্য বানানো LLM নয়। মিল যথেষ্ট না হলে চুপ থাকবে।", 13f)
        val question = input("প্রশ্ন বা বিষয়")
        val keywords = input("ঐচ্ছিক কীওয়ার্ড (কমা দিয়ে)")
        val answer = input("উত্তর", multiline = true)
        button("Knowledge entry সেভ (যোগ/পরিবর্তন)") {
            val q = question.text.toString().trim()
            val a = answer.text.toString().trim()
            if (q.isBlank() || a.isBlank()) {
                toast("প্রশ্ন এবং উত্তর দুটোই দিন")
            } else {
                val entry = KnowledgeEntry(q, a, keywords.text.toString().trim())
                val updated = settings.knowledge.toMutableList()
                val at = editKnowledgeIndex
                if (at == null) updated.add(entry) else if (at in updated.indices) updated[at] = entry
                editKnowledgeIndex = null
                updateSettings(settings.copy(knowledge = updated))
            }
        }
        button("JSON knowledge_base ফাইল ইমপোর্ট") {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/json"
            }
            startActivityForResult(intent, REQUEST_IMPORT)
        }
        button("উদাহরণ knowledge base লোড (বর্তমানটি বদলাবে)") { loadExampleKnowledge() }
        button("বর্তমান knowledge_base.json ফাইল দেখুন") {
            toast("ফাইলটি অ্যাপের private storage-এ: ${filesDir}/knowledge_base.json")
        }
        if (settings.knowledge.isEmpty()) text("Knowledge base খালি—কোনো উত্তর পাঠানো হবে না।", 13f)
        settings.knowledge.forEachIndexed { index, entry ->
            val container = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(10), dp(8), dp(10), dp(8))
                setBackgroundColor(0xFFFFFFFF.toInt())
            }
            container.addView(TextView(this).apply {
                text = "Q: ${entry.question}\nA: ${entry.answer}"
                textSize = 14f
            })
            val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            actions.addView(Button(this).apply {
                text = "Edit"
                setOnClickListener {
                    editKnowledgeIndex = index
                    question.setText(entry.question)
                    keywords.setText(entry.keywords)
                    answer.setText(entry.answer)
                    question.requestFocus()
                    scrollToTop()
                }
            })
            actions.addView(Button(this).apply {
                text = "Delete"
                setOnClickListener {
                    editKnowledgeIndex = null
                    updateSettings(settings.copy(knowledge = settings.knowledge.filterIndexed { i, _ -> i != index }))
                }
            })
            container.addView(actions)
            root.addView(container, params())
            space(6)
        }

        section("৪. WhatsApp কল")
        text("ব্যক্তিগত WhatsApp অ্যাপের incoming call auto-accept/decline করার supported public API নেই। কিছু ফোন/সংস্করণে notification action দেখা গেলেও তা ভরসাযোগ্য বা সব সংস্করণে উন্মুক্ত—এমন নিশ্চয়তা নেই। এই prototype কল নিয়ন্ত্রণ বা নজরদারি করে না; কোনো কল ধরবে বা কাটবে না।", 13f)
        val callToggle = Switch(this).apply {
            text = "কল অটো-হ্যান্ডলিং (অসমর্থিত — নিষ্ক্রিয়)"
            isChecked = settings.callAutomationEnabled
            isEnabled = false
            setOnCheckedChangeListener { _, checked ->
                updateSettings(settings.copy(callAutomationEnabled = checked))
            }
        }
        root.addView(callToggle)
        text("প্রতিটি পরিবর্তন স্বয়ংক্রিয়ভাবে সেভ হয়।", 12f)
    }

    private fun updateSettings(value: AppSettings) {
        settings = value
        SettingsStore.save(this, value)
        writeKnowledgeFile(value.knowledge)
        render()
    }

    private fun writeKnowledgeFile(entries: List<KnowledgeEntry>) {
        val json = JSONArray().apply {
            entries.forEach { entry ->
                put(JSONObject().put("question", entry.question).put("answer", entry.answer).put("keywords", entry.keywords))
            }
        }
        try { openFileOutput("knowledge_base.json", MODE_PRIVATE).use { it.write(json.toString(2).toByteArray(Charsets.UTF_8)) } }
        catch (_: Exception) { toast("Knowledge base ফাইল সেভ করা যায়নি") }
    }

    private fun importKnowledge(uri: Uri) {
        try {
            val raw = contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                ?: throw IllegalArgumentException("ফাইল পড়া যায়নি")
            applyKnowledgeJson(raw)
        } catch (e: Exception) {
            toast("JSON ইমপোর্ট হয়নি: ${e.message ?: "ভুল ফাইল ফরম্যাট"}")
        }
    }

    private fun loadExampleKnowledge() {
        try {
            val raw = assets.open("knowledge_base.example.json").bufferedReader().use { it.readText() }
            applyKnowledgeJson(raw)
        } catch (e: Exception) {
            toast("নমুনা knowledge base লোড হয়নি: ${e.message}")
        }
    }

    private fun applyKnowledgeJson(raw: String) {
        val parsed = JSONArray(raw)
        val entries = (0 until parsed.length()).mapNotNull { i ->
            val obj = parsed.optJSONObject(i) ?: return@mapNotNull null
            val q = obj.optString("question").trim()
            val a = obj.optString("answer").trim()
            if (q.isBlank() || a.isBlank()) null else KnowledgeEntry(q, a, obj.optString("keywords"))
        }
        updateSettings(settings.copy(knowledge = entries))
        toast("${entries.size}টি knowledge entry সেভ হয়েছে")
    }

    @Deprecated("Uses the system document picker for a JSON file")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_IMPORT && resultCode == Activity.RESULT_OK) data?.data?.let(::importKnowledge)
    }

    private fun isNotificationAccessEnabled(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        return enabled.split(":").any { component -> component.substringBefore('/') == packageName }
    }

    private fun section(label: String) {
        space(12)
        root.addView(TextView(this).apply {
            text = label
            textSize = 18f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(0xFF075E45.toInt())
            setPadding(0, dp(8), 0, dp(4))
        })
    }

    private fun text(value: String, size: Float, bold: Boolean = false) {
        root.addView(TextView(this).apply {
            text = value
            textSize = size
            if (bold) setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(4), 0, dp(4))
        })
    }

    private fun input(hintText: String, multiline: Boolean = false): EditText {
        return EditText(this).apply {
            hint = hintText
            textSize = 15f
            if (multiline) {
                minLines = 3
                gravity = Gravity.TOP or Gravity.START
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
            }
            root.addView(this, params())
        }
    }

    private fun toggle(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
        root.addView(Switch(this).apply {
            text = label
            isChecked = checked
            setOnCheckedChangeListener { _, value -> onChange(value) }
        })
    }

    private fun button(label: String, action: () -> Unit) {
        root.addView(Button(this).apply { text = label; setOnClickListener { action() } }, params())
    }

    private fun row(label: String, actionLabel: String, action: () -> Unit) {
        val line = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        line.addView(TextView(this).apply { text = label; textSize = 14f }, LinearLayout.LayoutParams(0, -2, 1f))
        line.addView(Button(this).apply { text = actionLabel; setOnClickListener { action() } })
        root.addView(line)
    }

    private fun params() = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) }
    private fun space(height: Int) { root.addView(View(this), LinearLayout.LayoutParams(1, dp(height))) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    private fun scrollToTop() { (root.parent as? ScrollView)?.smoothScrollTo(0, 0) }

    companion object { private const val REQUEST_IMPORT = 4711 }
}
