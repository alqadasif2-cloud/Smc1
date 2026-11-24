package com.smc.phone

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.CheckBox
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.tabs.TabLayout
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.ProtocolException
import java.net.URL
import java.net.URLEncoder
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    companion object {
        // Default Firebase Firestore configuration (shared database wired to PC & Web)
        private const val DEFAULT_FB_PROJECT_ID = "gen-lang-client-0819396986"
        private const val DEFAULT_FB_DATABASE_ID = "ai-studio-remotecontrolsyn-df2f1204-af22-4100-8861-97c8a605fa68"
        private const val DEFAULT_FB_API_KEY = "AIzaSyCtdkKUAcEa5pZjKxxk1t9HayIq_Pi-ehw"
        private const val DEFAULT_FB_URL = "firestore://$DEFAULT_FB_PROJECT_ID/$DEFAULT_FB_DATABASE_ID"
        private const val DEFAULT_PAIR_CODE = "SMC-AUTO-BRIDGE"

        private const val BRIDGE_UDP_PORT = 8766
        private const val PREFS_NAME = "smc_phone_prefs"

        private val TF_NAMES = listOf("M1", "M5", "M15", "M30", "H1", "H4", "D1")
        private val DEFAULT_PROVIDERS = listOf(
            "Gemini",
            "Claude (عبر API)",
            "Claude Code (مباشر بدون API)"
        )
        private val DEFAULT_GEM_MODELS = listOf(
            "gemini-flash-latest", "gemini-pro-latest", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"
        )
        private val DEFAULT_CLAUDE_MODELS = listOf(
            "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4-5"
        )
        private val DEFAULT_TG_MODES = listOf("يدوي", "تلقائي")
        private val MODE_LABELS = listOf(
            "تلقائي (محلي ثم Firebase)",
            "محلي فقط (Wi-Fi)",
            "Firebase فقط"
        )
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private val netExec = Executors.newCachedThreadPool()

    // Connection settings
    private var pairCode = ""
    private var connModeIdx = 0 // 0=Auto, 1=Local, 2=Firebase
    private var fbUrl = DEFAULT_FB_URL
    private var fbSecret = DEFAULT_FB_API_KEY
    private var manualLocalUrl = ""
    private var discoveredLocalUrl = ""
    private var activeChannel = "none" // "local" | "firebase" | "none"
    private var lastLocalScanMs = 0L
    private var pollingActive = false
    private var isSyncingUi = false

    // Latest synced state & contents
    private var lastSnap: JSONObject? = null
    private val localVers = mutableMapOf<String, Int>()
    private val loadedVers = mutableMapOf<String, Int>()
    private var dataText = ""
    private var fileText = ""
    private var fileName = "SMC_request.txt"
    private var answerText = ""
    private var promptText = ""
    private var lastListsJson = ""

    private var symbolItems = mutableListOf("XAUUSD")
    private var providerItems = DEFAULT_PROVIDERS.toMutableList()
    private var gemModelItems = DEFAULT_GEM_MODELS.toMutableList()
    private var claudeModelItems = DEFAULT_CLAUDE_MODELS.toMutableList()
    private var tgModeItems = DEFAULT_TG_MODES.toMutableList()
    private var presetItems = mutableListOf<String>()

    // Header / Status Views
    private lateinit var tvPcHeader: TextView
    private lateinit var tvChannelBadge: TextView
    private lateinit var tvMt5Status: TextView
    private lateinit var tvLivePrice: TextView
    private lateinit var tvStatusBar: TextView
    private lateinit var progressBusy: ProgressBar
    private lateinit var tabLayout: TabLayout
    private val tabContainers = mutableListOf<View>()

    // Tab 1: Control views
    private lateinit var spSymbol: Spinner
    private val tfChecks = mutableMapOf<String, CheckBox>()
    private lateinit var cbChain: CheckBox
    private lateinit var spProvider: Spinner
    private lateinit var spGemModel: Spinner
    private lateinit var spClaudeModel: Spinner
    private lateinit var spTgMode: Spinner
    private lateinit var btnConnect: MaterialButton
    private lateinit var btnFetch: MaterialButton
    private lateinit var btnMakeFile: MaterialButton
    private lateinit var btnReceiveFile: MaterialButton
    private lateinit var btnWorkflowDownload: MaterialButton
    private lateinit var btnAi: MaterialButton
    private lateinit var btnFetchAi: MaterialButton
    private lateinit var btnTgAnswer: MaterialButton
    private lateinit var btnTgFile: MaterialButton
    private lateinit var btnModels: MaterialButton
    private lateinit var btnSavePc: MaterialButton
    private lateinit var btnStop: MaterialButton

    // Tab 2: Prompts views
    private lateinit var spPreset: Spinner
    private lateinit var etPrompt: EditText

    // Tab 3: Data views
    private lateinit var tvDataContent: TextView

    // Tab 4: File views
    private lateinit var tvFileNameLabel: TextView
    private lateinit var tvFileContent: TextView

    // Tab 5: Answer views
    private lateinit var tvAnswerLabel: TextView
    private lateinit var tvAnswerContent: TextView

    // Tab 6: Log & Settings views
    private lateinit var tvLogContent: TextView
    private lateinit var etPairCode: EditText
    private lateinit var spConnMode: Spinner
    private lateinit var etManualLocal: EditText
    private lateinit var etFbUrl: EditText
    private lateinit var etFbSecret: EditText
    private lateinit var tvDiagInfo: TextView

    private val pollRunnable = object : Runnable {
        override fun run() {
            if (!pollingActive) return
            pollOnce()
            mainHandler.postDelayed(this, 1800)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        loadPrefs()
        buildUi()
        applyPrefsToSettingsUi()
    }

    override fun onResume() {
        super.onResume()
        pollingActive = true
        mainHandler.removeCallbacks(pollRunnable)
        mainHandler.post(pollRunnable)
        if (normCode(pairCode).length >= 12 && connModeIdx != 2) {
            scanLocalNetworkAsync(silent = true)
        }
    }

    override fun onPause() {
        super.onPause()
        pollingActive = false
        mainHandler.removeCallbacks(pollRunnable)
    }

    override fun onDestroy() {
        super.onDestroy()
        netExec.shutdownNow()
    }

    // ==========================================================
    // Preferences
    // ==========================================================
    private fun loadPrefs() {
        val p = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        pairCode = p.getString("pair_code", DEFAULT_PAIR_CODE)?.ifBlank { DEFAULT_PAIR_CODE } ?: DEFAULT_PAIR_CODE
        connModeIdx = p.getInt("conn_mode", 0).coerceIn(0, 2)
        fbUrl = p.getString("fb_url", DEFAULT_FB_URL)?.ifBlank { DEFAULT_FB_URL } ?: DEFAULT_FB_URL
        fbSecret = p.getString("fb_secret", DEFAULT_FB_API_KEY)?.ifBlank { DEFAULT_FB_API_KEY } ?: DEFAULT_FB_API_KEY
        manualLocalUrl = p.getString("manual_local", "") ?: ""
    }

    private fun savePrefs() {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString("pair_code", pairCode)
            .putInt("conn_mode", connModeIdx)
            .putString("fb_url", fbUrl)
            .putString("fb_secret", fbSecret)
            .putString("manual_local", manualLocalUrl)
            .apply()
    }

    private fun normCode(c: String?): String {
        return (c ?: "").replace(Regex("[^A-Za-z0-9]"), "").uppercase(Locale.US)
    }

    // ==========================================================
    // UI Construction (Single-File Material RTL Layout)
    // ==========================================================
    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            setBackgroundColor(Color.parseColor("#F1F5F9"))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Top Header Card
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A"))
            setPadding(dp(14), dp(12), dp(14), dp(10))
        }

        val topRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        tvPcHeader = TextView(this).apply {
            text = "SMC Phone — التحكم عن بُعد"
            setTextColor(Color.WHITE)
            textSize = 16f
            setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        tvChannelBadge = TextView(this).apply {
            text = "جاري الاتصال..."
            setTextColor(Color.parseColor("#E2E8F0"))
            textSize = 12f
        }
        topRow.addView(tvPcHeader)
        topRow.addView(tvChannelBadge)
        header.addView(topRow)

        val statusRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(6), 0, 0)
        }
        tvMt5Status = TextView(this).apply {
            text = "● MT5 غير متصل"
            setTextColor(Color.parseColor("#FCA5A5"))
            textSize = 12f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        tvLivePrice = TextView(this).apply {
            text = "—"
            setTextColor(Color.parseColor("#38BDF8"))
            textSize = 13f
            setTypeface(Typeface.MONOSPACE, Typeface.BOLD)
        }
        statusRow.addView(tvMt5Status)
        statusRow.addView(tvLivePrice)
        header.addView(statusRow)

        val barRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(4), 0, 0)
        }
        progressBusy = ProgressBar(this, null, android.R.attr.progressBarStyleSmall).apply {
            visibility = View.GONE
            setPadding(0, 0, dp(6), 0)
        }
        tvStatusBar = TextView(this).apply {
            text = "متصل تلقائياً عبر Firebase / الشبكة المحلية — في انتظار السكربت على الكمبيوتر"
            setTextColor(Color.parseColor("#CBD5E1"))
            textSize = 12f
        }
        barRow.addView(progressBusy)
        barRow.addView(tvStatusBar)
        header.addView(barRow)

        root.addView(header)

        // Tabs
        tabLayout = TabLayout(this).apply {
            tabMode = TabLayout.MODE_SCROLLABLE
            setBackgroundColor(Color.WHITE)
            setSelectedTabIndicatorColor(Color.parseColor("#0F172A"))
            setTabTextColors(Color.parseColor("#64748B"), Color.parseColor("#0F172A"))
        }
        val tabTitles = listOf("التحكم", "الأوامر", "البيانات", "الملف txt", "التحليل", "السجل والربط")
        tabTitles.forEach { title -> tabLayout.addTab(tabLayout.newTab().setText(title)) }
        root.addView(tabLayout)

        // Content Frame
        val contentHost = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        }

        val t1 = buildControlTab()
        val t2 = buildPromptsTab()
        val t3 = buildDataTab()
        val t4 = buildFileTab()
        val t5 = buildAnswerTab()
        val t6 = buildLogBridgeTab()
        tabContainers.addAll(listOf(t1, t2, t3, t4, t5, t6))
        tabContainers.forEachIndexed { idx, view ->
            view.visibility = if (idx == 0) View.VISIBLE else View.GONE
            contentHost.addView(view)
        }
        root.addView(contentHost)

        tabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                tabContainers.forEachIndexed { idx, v ->
                    v.visibility = if (idx == tab.position) View.VISIBLE else View.GONE
                }
            }
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })

        setContentView(root)
    }

    private fun card(parent: LinearLayout, title: String): LinearLayout {
        val c = MaterialCardView(this).apply {
            radius = dp(10).toFloat()
            cardElevation = dp(1).toFloat()
            setCardBackgroundColor(Color.WHITE)
            strokeColor = Color.parseColor("#CBD5E1")
            strokeWidth = dp(1)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, dp(10)) }
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
        }
        if (title.isNotEmpty()) {
            inner.addView(TextView(this).apply {
                text = title
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 14f
                setTypeface(typeface, Typeface.BOLD)
                setPadding(0, 0, 0, dp(8))
            })
        }
        c.addView(inner)
        parent.addView(c)
        return inner
    }

    private fun makeBtn(label: String, bgHex: String, textHex: String = "#FFFFFF", onClick: () -> Unit): MaterialButton {
        return MaterialButton(this).apply {
            text = label
            setTextColor(Color.parseColor(textHex))
            setBackgroundColor(Color.parseColor(bgHex))
            cornerRadius = dp(8)
            textSize = 13f
            isAllCaps = false
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, dp(4), 0, dp(4)) }
        }
    }

    private fun labelRow(parent: LinearLayout, label: String): Spinner {
        parent.addView(TextView(this).apply {
            text = label
            setTextColor(Color.parseColor("#475569"))
            textSize = 12f
            setPadding(0, dp(4), 0, dp(2))
        })
        val sp = Spinner(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, dp(6)) }
        }
        parent.addView(sp)
        return sp
    }

    private fun setSpinnerItems(sp: Spinner, items: List<String>, selected: String? = null) {
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, items).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }
        sp.adapter = adapter
        if (!selected.isNullOrBlank()) {
            val idx = items.indexOf(selected)
            if (idx >= 0) sp.setSelection(idx, false)
        }
    }

    // ---------- Tab 1: Control ----------
    private fun buildControlTab(): View {
        val scroll = ScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(24))
        }

        // Card 1: MT5 & Symbol
        val c1 = card(box, "1) منصة MT5 والرمز")
        btnConnect = makeBtn("🔌 اتصال / إعادة اتصال MT5", "#0F172A") { sendAction("connect") }
        c1.addView(btnConnect)

        spSymbol = labelRow(c1, "الرمز (Symbol)")
        setSpinnerItems(spSymbol, symbolItems, "XAUUSD")
        spSymbol.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                if (!isSyncingUi) sendSettingsOnly()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        // Card 2: Timeframes
        val c2 = card(box, "2) الفريمات")
        val tfWrap = HorizontalScrollView(this)
        val tfRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        TF_NAMES.forEach { tf ->
            val cb = CheckBox(this).apply {
                text = tf
                isChecked = (tf != "D1")
                setOnCheckedChangeListener { _, _ -> if (!isSyncingUi) sendSettingsOnly() }
            }
            tfChecks[tf] = cb
            tfRow.addView(cb)
        }
        tfWrap.addView(tfRow)
        c2.addView(tfWrap)

        cbChain = CheckBox(this).apply {
            text = "تحليل تلقائياً بعد الجلب"
            setOnCheckedChangeListener { _, _ -> if (!isSyncingUi) sendSettingsOnly() }
        }
        c2.addView(cbChain)

        // Card 3: AI Providers & Models
        val c3 = card(box, "3) مزوّد التحليل و Telegram")
        spProvider = labelRow(c3, "مزوّد التحليل")
        setSpinnerItems(spProvider, providerItems, providerItems.first())
        spProvider.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!isSyncingUi) sendSettingsOnly()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        spGemModel = labelRow(c3, "موديل Gemini")
        setSpinnerItems(spGemModel, gemModelItems, gemModelItems.first())
        spGemModel.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!isSyncingUi) sendSettingsOnly()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        spClaudeModel = labelRow(c3, "موديل Claude")
        setSpinnerItems(spClaudeModel, claudeModelItems, claudeModelItems.first())
        spClaudeModel.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!isSyncingUi) sendSettingsOnly()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        spTgMode = labelRow(c3, "إرسال النتيجة لـ Telegram")
        setSpinnerItems(spTgMode, tgModeItems, tgModeItems.first())
        spTgMode.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!isSyncingUi) sendSettingsOnly()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        btnModels = makeBtn("🔄 تحديث قوائم الموديلات", "#334155") { sendAction("models") }
        c3.addView(btnModels)

        // Card 4: Action Buttons (1:1 mirror of Desktop Panel + Mobile File Receive)
        val c4 = card(box, "4) أزرار التنفيذ وإرسال الملفات للهاتف")
        btnFetch = makeBtn("📥 جلب البيانات الحية", "#0369A1") {
            sendAction("fetch", collectParams(), pullContentAfter = "data")
        }
        btnMakeFile = makeBtn("📄 إنشاء الملف فقط (.txt)", "#1D4ED8") {
            sendAction("make_file", collectParams(), pullContentAfter = "file")
        }
        btnReceiveFile = makeBtn("⬇️ رفع / استلام الملف إلى الهاتف وحفظه", "#047857") {
            pullContentAndSaveFile()
        }
        btnWorkflowDownload = makeBtn("⚡ جلب + إنشاء ملف + استلام للهاتف", "#0F766E") {
            runFetchCreateAndDownloadWorkflow()
        }
        btnAi = makeBtn("🤖 إنشاء الملف وإرساله للمزوّد", "#4338CA") {
            sendAction("ai", collectParams(), pullContentAfter = "answer")
        }
        btnFetchAi = makeBtn("⚡ جلب + تحليل", "#6D28D9") {
            sendAction("fetch_ai", collectParams(), pullContentAfter = "answer")
        }
        btnTgAnswer = makeBtn("📨 إرسال النتيجة إلى Telegram", "#0284C7") {
            sendAction("tg_answer")
        }
        btnTgFile = makeBtn("📎 إنشاء ملف وإرساله إلى Telegram", "#0E7490") {
            sendAction("tg_file")
        }
        btnSavePc = makeBtn("💾 حفظ الإعدادات على الكمبيوتر", "#475569") {
            sendAction("save")
        }
        btnStop = makeBtn("⏹ إيقاف العملية الحالية", "#DC2626") {
            sendAction("stop")
        }

        listOf(
            btnFetch, btnMakeFile, btnReceiveFile, btnWorkflowDownload,
            btnAi, btnFetchAi, btnTgAnswer, btnTgFile, btnSavePc, btnStop
        ).forEach { c4.addView(it) }

        scroll.addView(box)
        return scroll
    }

    // ---------- Tab 2: Prompts ----------
    private fun buildPromptsTab(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        spPreset = labelRow(box, "أوامر جاهزة لإضافتها")
        setSpinnerItems(spPreset, listOf("اختر أمراً جاهزاً..."))

        val rowBtns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bAdd = MaterialButton(this).apply {
            text = "➕ إضافة"
            isAllCaps = false
            setOnClickListener {
                val p = spPreset.selectedItem?.toString() ?: ""
                if (p.isNotBlank() && !p.startsWith("اختر")) {
                    val cur = etPrompt.text.toString().trimEnd()
                    etPrompt.setText(if (cur.isEmpty()) p else "$cur\n$p")
                }
            }
        }
        val bSavePrompt = MaterialButton(this).apply {
            text = "💾 حفظ الأوامر"
            isAllCaps = false
            setOnClickListener {
                sendAction("set_prompt", JSONObject().put("text", etPrompt.text.toString()))
            }
        }
        val bResetPrompt = MaterialButton(this).apply {
            text = "↩ استعادة"
            isAllCaps = false
            setOnClickListener {
                sendAction("reset_prompt", pullContentAfter = "prompt")
            }
        }
        listOf(bAdd, bSavePrompt, bResetPrompt).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            rowBtns.addView(b)
        }
        box.addView(rowBtns)

        etPrompt = EditText(this).apply {
            gravity = Gravity.TOP or Gravity.START
            textAlignment = View.TEXT_ALIGNMENT_VIEW_START
            setBackgroundColor(Color.WHITE)
            setPadding(dp(10), dp(10), dp(10), dp(10))
            textSize = 14f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        box.addView(etPrompt)
        return box
    }

    // ---------- Tab 3: Data ----------
    private fun buildDataTab(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val b1 = makeBtn("📥 جلب البيانات الحية", "#0369A1") {
            sendAction("fetch", collectParams(), pullContentAfter = "data")
        }
        val b2 = makeBtn("🔄 سحب أحدث بيانات", "#334155") {
            pullContentAsync("data", saveToDownloads = false)
        }
        val b3 = makeBtn("📋 نسخ", "#475569") { copyText("البيانات", dataText) }
        listOf(b1, b2, b3).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            row.addView(b)
        }
        box.addView(row)

        val sc = ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvDataContent = TextView(this).apply {
            text = "لا توجد بيانات مجلوبة بعد — اضغط 'جلب البيانات الحية'."
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setTextIsSelectable(true)
            typeface = Typeface.MONOSPACE
            textSize = 12f
        }
        sc.addView(tvDataContent)
        box.addView(sc)
        return box
    }

    // ---------- Tab 4: File (.txt) ----------
    private fun buildFileTab(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        tvFileNameLabel = TextView(this).apply {
            text = "الملف الحالي: لا يوجد"
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        box.addView(tvFileNameLabel)

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bCreate = makeBtn("📄 إنشاء الملف", "#1D4ED8") {
            sendAction("make_file", collectParams(), pullContentAfter = "file")
        }
        val bPullSave = makeBtn("⬇️ استلام وحفظ للهاتف", "#047857") {
            pullContentAndSaveFile()
        }
        val bShare = makeBtn("📤 مشاركة", "#0F172A") {
            shareFileText()
        }
        listOf(bCreate, bPullSave, bShare).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            row.addView(b)
        }
        box.addView(row)

        val sc = ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvFileContent = TextView(this).apply {
            text = "لم يتم إنشاء أو استلام ملف بعد."
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setTextIsSelectable(true)
            typeface = Typeface.MONOSPACE
            textSize = 12f
        }
        sc.addView(tvFileContent)
        box.addView(sc)
        return box
    }

    // ---------- Tab 5: Answer ----------
    private fun buildAnswerTab(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        tvAnswerLabel = TextView(this).apply {
            text = "نتيجة التحليل"
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        box.addView(tvAnswerLabel)

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bCopy = makeBtn("📋 نسخ النتيجة", "#334155") { copyText("النتيجة", answerText) }
        val bTg = makeBtn("📨 إرسال لـ Telegram", "#0284C7") { sendAction("tg_answer") }
        val bShare = makeBtn("📤 مشاركة", "#0F172A") { sharePlainText(answerText, "نتيجة تحليل SMC") }
        listOf(bCopy, bTg, bShare).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            row.addView(b)
        }
        box.addView(row)

        val sc = ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvAnswerContent = TextView(this).apply {
            text = "لا توجد نتيجة تحليل بعد."
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setTextIsSelectable(true)
            textSize = 14f
        }
        sc.addView(tvAnswerContent)
        box.addView(sc)
        return box
    }

    // ---------- Tab 6: Log & Connection Settings ----------
    private fun buildLogBridgeTab(): View {
        val scroll = ScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(24))
        }

        val cConn = card(box, "إعدادات الربط (تلقائي: محلي Wi-Fi + Firebase افتراضياً)")
        cConn.addView(TextView(this).apply { text = "رمز الربط (من القسم 4 في اللوحة الأم على الكمبيوتر)"; textSize = 12f })
        etPairCode = EditText(this).apply {
            hint = "مثال: ABCD-EFGH-JKLM"
            isSingleLine = true
        }
        cConn.addView(etPairCode)

        spConnMode = labelRow(cConn, "طريقة الاتصال")
        setSpinnerItems(spConnMode, MODE_LABELS, MODE_LABELS[connModeIdx])

        cConn.addView(TextView(this).apply { text = "عنوان المحلي اليدوي (اختياري، مثال: http://192.168.1.10:8765)"; textSize = 12f })
        etManualLocal = EditText(this).apply {
            hint = "http://192.168.1.x:8765"
            isSingleLine = true
        }
        cConn.addView(etManualLocal)

        cConn.addView(TextView(this).apply { text = "رابط Firebase (مربوط افتراضياً)"; textSize = 12f })
        etFbUrl = EditText(this).apply { isSingleLine = true }
        cConn.addView(etFbUrl)

        cConn.addView(TextView(this).apply { text = "مفتاح Firebase API Key / Secret"; textSize = 12f })
        etFbSecret = EditText(this).apply {
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        cConn.addView(etFbSecret)

        cConn.addView(makeBtn("💾 حفظ الإعدادات وتطبيق الربط", "#0F172A") {
            pairCode = etPairCode.text.toString().trim().uppercase(Locale.US)
            connModeIdx = spConnMode.selectedItemPosition.coerceIn(0, 2)
            manualLocalUrl = etManualLocal.text.toString().trim().trimEnd('/')
            fbUrl = etFbUrl.text.toString().trim().ifBlank { DEFAULT_FB_URL }
            fbSecret = etFbSecret.text.toString().trim().ifBlank { DEFAULT_FB_API_KEY }
            savePrefs()
            toast("تم حفظ إعدادات الربط")
            if (connModeIdx != 2) scanLocalNetworkAsync(silent = false)
            pollOnce()
        })

        cConn.addView(makeBtn("🔍 مسح الشبكة المحلية (Wi-Fi) الآن", "#0369A1") {
            scanLocalNetworkAsync(silent = false)
        })

        cConn.addView(makeBtn("↩ استعادة إعدادات Firebase الافتراضية", "#475569") {
            fbUrl = DEFAULT_FB_URL
            fbSecret = DEFAULT_FB_API_KEY
            connModeIdx = 0
            savePrefs()
            applyPrefsToSettingsUi()
            toast("تمت استعادة Firebase الافتراضي")
        })

        tvDiagInfo = TextView(this).apply {
            text = "الحالة: في انتظار الاتصال..."
            textSize = 12f
            setPadding(0, dp(6), 0, 0)
        }
        cConn.addView(tvDiagInfo)

        val cLog = card(box, "سجل الكمبيوتر المباشر")
        tvLogContent = TextView(this).apply {
            text = "—"
            typeface = Typeface.MONOSPACE
            textSize = 11f
            setTextIsSelectable(true)
        }
        cLog.addView(tvLogContent)

        scroll.addView(box)
        return scroll
    }

    private fun applyPrefsToSettingsUi() {
        etPairCode.setText(pairCode)
        spConnMode.setSelection(connModeIdx)
        etManualLocal.setText(manualLocalUrl)
        etFbUrl.setText(fbUrl)
        etFbSecret.setText(fbSecret)
    }

    // ==========================================================
    // Networking: Local Auto-Discovery + HTTP + Firebase Firestore REST
    // ==========================================================
    private fun collectParams(): JSONObject {
        val tfsObj = JSONObject()
        TF_NAMES.forEach { tf -> tfsObj.put(tf, tfChecks[tf]?.isChecked == true) }
        return JSONObject().apply {
            put("symbol", spSymbol.selectedItem?.toString() ?: "XAUUSD")
            put("tfs", tfsObj)
            put("chain", cbChain.isChecked)
            put("provider", spProvider.selectedItem?.toString() ?: DEFAULT_PROVIDERS.first())
            put("gem_model", spGemModel.selectedItem?.toString() ?: DEFAULT_GEM_MODELS.first())
            put("claude_model", spClaudeModel.selectedItem?.toString() ?: DEFAULT_CLAUDE_MODELS.first())
            put("tg_mode", spTgMode.selectedItem?.toString() ?: "يدوي")
        }
    }

    private fun scanLocalNetworkAsync(silent: Boolean) {
        netExec.execute {
            val found = discoverLocalServer()
            if (found != null) {
                discoveredLocalUrl = found
                mainHandler.post {
                    if (!silent) toast("تم اكتشاف اللوحة محلياً: $found")
                    tvDiagInfo.text = "محلي مكتشف: $found"
                }
            } else if (!silent) {
                mainHandler.post {
                    toast("لم يُعثر على الكمبيوتر في الشبكة المحلية — سيتم استخدام Firebase تلقائياً")
                }
            }
        }
    }

    private fun discoverLocalServer(): String? {
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val lock = try { wifi?.createMulticastLock("smc_discover")?.apply { setReferenceCounted(false); acquire() } } catch (_: Throwable) { null }
        var sock: DatagramSocket? = null
        try {
            sock = DatagramSocket().apply {
                broadcast = true
                soTimeout = 1300
            }
            val payload = "SMC_DISCOVER".toByteArray(Charsets.UTF_8)
            val targets = linkedSetOf(InetAddress.getByName("255.255.255.255"))
            try {
                val interfaces = NetworkInterface.getNetworkInterfaces()
                while (interfaces.hasMoreElements()) {
                    val nif = interfaces.nextElement()
                    if (!nif.isUp || nif.isLoopback) continue
                    for (ia in nif.interfaceAddresses) {
                        ia.broadcast?.let { targets.add(it) }
                    }
                }
            } catch (_: Throwable) {}

            for (addr in targets) {
                try {
                    sock.send(DatagramPacket(payload, payload.size, addr, BRIDGE_UDP_PORT))
                } catch (_: Throwable) {}
            }

            val buf = ByteArray(1024)
            val pkt = DatagramPacket(buf, buf.size)
            sock.receive(pkt)
            val txt = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
            val js = JSONObject(txt)
            if (js.optInt("smc") == 1 && js.optInt("port") > 0) {
                return "http://${pkt.address.hostAddress}:${js.optInt("port")}"
            }
        } catch (_: Throwable) {
        } finally {
            try { sock?.close() } catch (_: Throwable) {}
            try { if (lock?.isHeld == true) lock.release() } catch (_: Throwable) {}
        }
        return null
    }

    private fun candidateLocalUrl(): String {
        val m = manualLocalUrl.trim().trimEnd('/')
        if (m.isNotBlank()) return if (m.startsWith("http")) m else "http://$m"
        return discoveredLocalUrl
    }

    private fun isFirestoreUrl(u: String): Boolean {
        return u.startsWith("firestore://") || u.contains("firestore.googleapis.com")
    }

    private fun firestoreBaseUrl(): String {
        val u = fbUrl.trim()
        if (u.startsWith("firestore://")) {
            val rest = u.removePrefix("firestore://").trim('/')
            val parts = rest.split('/', limit = 2)
            val proj = parts.getOrNull(0)?.ifBlank { DEFAULT_FB_PROJECT_ID } ?: DEFAULT_FB_PROJECT_ID
            val db = parts.getOrNull(1)?.ifBlank { "(default)" } ?: "(default)"
            return "https://firestore.googleapis.com/v1/projects/$proj/databases/$db/documents"
        }
        return u.trimEnd('/')
    }

    private fun httpJson(
        urlStr: String,
        method: String = "GET",
        bodyStr: String? = null,
        headers: Map<String, String> = emptyMap(),
        timeoutMs: Int = 6000
    ): Pair<Int, String> {
        val url = URL(urlStr)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            setRequestProperty("Accept", "application/json")
            headers.forEach { (k, v) -> setRequestProperty(k, v) }
            try {
                requestMethod = method
            } catch (_: ProtocolException) {
                if (method == "PATCH") {
                    requestMethod = "POST"
                    setRequestProperty("X-HTTP-Method-Override", "PATCH")
                } else {
                    throw ProtocolException("Unsupported method: $method")
                }
            }
            if (bodyStr != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                outputStream.use { it.write(bodyStr.toByteArray(Charsets.UTF_8)) }
            }
        }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = if (stream != null) BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() } else ""
        conn.disconnect()
        return code to text
    }

    private fun fsEncodeValue(v: Any?): JSONObject {
        return when (v) {
            is Boolean -> JSONObject().put("booleanValue", v)
            is Int -> JSONObject().put("integerValue", v.toString())
            is Long -> JSONObject().put("integerValue", v.toString())
            is Double -> JSONObject().put("doubleValue", v)
            else -> JSONObject().put("stringValue", (v ?: "").toString())
        }
    }

    private fun fsEncodeDoc(map: Map<String, Any?>): String {
        val fields = JSONObject()
        map.forEach { (k, v) -> if (v != null) fields.put(k, fsEncodeValue(v)) }
        return JSONObject().put("fields", fields).toString()
    }

    private fun fsDecodeDoc(rawJson: String): JSONObject {
        val out = JSONObject()
        val root = JSONObject(rawJson)
        val fields = root.optJSONObject("fields") ?: return out
        val keys = fields.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            val obj = fields.optJSONObject(k) ?: continue
            when {
                obj.has("stringValue") -> out.put(k, obj.optString("stringValue"))
                obj.has("booleanValue") -> out.put(k, obj.optBoolean("booleanValue"))
                obj.has("integerValue") -> out.put(k, obj.optString("integerValue").toLongOrNull() ?: 0L)
                obj.has("doubleValue") -> out.put(k, obj.optDouble("doubleValue"))
            }
        }
        return out
    }

    private fun fsRoomToState(doc: JSONObject): JSONObject {
        val tfsObj = try { JSONObject(doc.optString("tfsJson", "{}")) } catch (_: Throwable) { JSONObject() }
        val versObj = try { JSONObject(doc.optString("versJson", "{}")) } catch (_: Throwable) { JSONObject() }
        return JSONObject().apply {
            put("ok", doc.optInt("ok", 1))
            put("name", doc.optString("name", "PC"))
            put("mt5", doc.optBoolean("mt5", false))
            put("conn", doc.optString("conn", "● غير متصل"))
            put("busy", doc.optBoolean("busy", false))
            put("ai", doc.optBoolean("ai", false))
            put("status", doc.optString("status", ""))
            put("price", doc.optString("price", ""))
            put("symbol", doc.optString("symbol", "XAUUSD"))
            put("tfs", tfsObj)
            put("chain", doc.optBoolean("chain", false))
            put("provider", doc.optString("provider", DEFAULT_PROVIDERS.first()))
            put("gem_model", doc.optString("gem_model", DEFAULT_GEM_MODELS.first()))
            put("claude_model", doc.optString("claude_model", DEFAULT_CLAUDE_MODELS.first()))
            put("tg_mode", doc.optString("tg_mode", "يدوي"))
            put("label", doc.optString("label", ""))
            put("vers", versObj)
            put("log", doc.optString("log", ""))
            put("ts", doc.optLong("ts", 0L))
        }
    }

    private fun pollOnce() {
        val code = normCode(pairCode)
        if (code.length < 12) {
            mainHandler.post {
                tvChannelBadge.text = "🔴 أدخل رمز الربط"
                tvStatusBar.text = "افتح تبويب 'السجل والربط' وأدخل رمز الربط الموجود في القسم 4 على الكمبيوتر"
            }
            return
        }

        netExec.execute {
            var snap: JSONObject? = null
            var channel = "none"
            var errMsg = ""

            // 1) Try Local Wi-Fi first if Auto (0) or Local Only (1)
            if (connModeIdx == 0 || connModeIdx == 1) {
                var loc = candidateLocalUrl()
                if (loc.isBlank() && System.currentTimeMillis() - lastLocalScanMs > 15000L) {
                    lastLocalScanMs = System.currentTimeMillis()
                    loc = discoverLocalServer() ?: ""
                    if (loc.isNotBlank()) discoveredLocalUrl = loc
                }
                if (loc.isNotBlank()) {
                    try {
                        val (sc, body) = httpJson("$loc/state", "GET", headers = mapOf("X-Token" to code), timeoutMs = 1500)
                        if (sc == 200) {
                            snap = JSONObject(body)
                            channel = "local"
                        } else if (sc == 401) {
                            errMsg = "رمز الربط غير مطابق للكمبيوتر"
                        }
                    } catch (_: Throwable) {
                        if (loc == discoveredLocalUrl) discoveredLocalUrl = ""
                    }
                }
            }

            // 2) Fallback / Firebase mode if Auto (0) or Firebase Only (2)
            if (snap == null && (connModeIdx == 0 || connModeIdx == 2)) {
                val room = code.lowercase(Locale.US)
                try {
                    if (isFirestoreUrl(fbUrl)) {
                        val keyParam = URLEncoder.encode(fbSecret.ifBlank { DEFAULT_FB_API_KEY }, "UTF-8")
                        val url = "${firestoreBaseUrl()}/rooms/$room?key=$keyParam"
                        val (sc, body) = httpJson(url, "GET", timeoutMs = 7000)
                        if (sc == 200) {
                            snap = fsRoomToState(fsDecodeDoc(body))
                            channel = "firebase"
                        } else if (sc == 404) {
                            errMsg = "الغرفة غير موجودة بعد — شغّل السكربت على الكمبيوتر بنفس الرمز"
                        } else {
                            errMsg = "Firebase HTTP $sc"
                        }
                    } else {
                        val auth = if (fbSecret.isNotBlank()) "?auth=${URLEncoder.encode(fbSecret, "UTF-8")}" else ""
                        val url = "${fbUrl.trimEnd('/')}/rooms/$room/state.json$auth"
                        val (sc, body) = httpJson(url, "GET", timeoutMs = 7000)
                        if (sc == 200 && body.isNotBlank() && body != "null") {
                            snap = JSONObject(body)
                            channel = "firebase"
                        } else {
                            errMsg = "Firebase: لا توجد بيانات للغرفة"
                        }
                    }
                } catch (e: Throwable) {
                    errMsg = "تعذر الاتصال بـ Firebase: ${e.message ?: e.javaClass.simpleName}"
                }
            }

            mainHandler.post {
                activeChannel = channel
                if (snap != null) {
                    applySnapshotToUi(snap, channel)
                } else {
                    tvChannelBadge.text = "🔴 غير متصل"
                    if (errMsg.isNotBlank()) tvStatusBar.text = errMsg
                }
            }
        }
    }

    private fun applySnapshotToUi(snap: JSONObject, channel: String) {
        lastSnap = snap
        val pcName = snap.optString("name", "PC")
        tvPcHeader.text = "SMC Phone — $pcName"
        tvChannelBadge.text = if (channel == "local") "🟢 محلي (Wi-Fi)" else "☁️ Firebase متصل"

        val mt5Ok = snap.optBoolean("mt5", false)
        tvMt5Status.text = snap.optString("conn", if (mt5Ok) "● متصل" else "● غير متصل")
        tvMt5Status.setTextColor(Color.parseColor(if (mt5Ok) "#86EFAC" else "#FCA5A5"))

        val price = snap.optString("price", "")
        tvLivePrice.text = if (price.isNotBlank()) price else "—"

        val busy = snap.optBoolean("busy", false)
        val ai = snap.optBoolean("ai", false)
        progressBusy.visibility = if (busy || ai) View.VISIBLE else View.GONE
        btnStop.isEnabled = ai || busy
        tvStatusBar.text = snap.optString("status", "جاهز")

        isSyncingUi = true
        try {
            val sym = snap.optString("symbol", "XAUUSD")
            if (sym.isNotBlank() && !symbolItems.contains(sym)) {
                symbolItems.add(0, sym)
                setSpinnerItems(spSymbol, symbolItems, sym)
            } else {
                val idx = symbolItems.indexOf(sym)
                if (idx >= 0 && spSymbol.selectedItemPosition != idx) spSymbol.setSelection(idx, false)
            }

            val tfs = snap.optJSONObject("tfs")
            if (tfs != null) {
                TF_NAMES.forEach { tf ->
                    if (tfs.has(tf)) tfChecks[tf]?.isChecked = tfs.optBoolean(tf, false)
                }
            }
            cbChain.isChecked = snap.optBoolean("chain", false)

            val prov = snap.optString("provider", "")
            providerItems.indexOf(prov).takeIf { it >= 0 }?.let { if (spProvider.selectedItemPosition != it) spProvider.setSelection(it, false) }

            val gm = snap.optString("gem_model", "")
            if (gm.isNotBlank() && !gemModelItems.contains(gm)) {
                gemModelItems.add(0, gm)
                setSpinnerItems(spGemModel, gemModelItems, gm)
            } else {
                gemModelItems.indexOf(gm).takeIf { it >= 0 }?.let { if (spGemModel.selectedItemPosition != it) spGemModel.setSelection(it, false) }
            }

            val cm = snap.optString("claude_model", "")
            if (cm.isNotBlank() && !claudeModelItems.contains(cm)) {
                claudeModelItems.add(0, cm)
                setSpinnerItems(spClaudeModel, claudeModelItems, cm)
            } else {
                claudeModelItems.indexOf(cm).takeIf { it >= 0 }?.let { if (spClaudeModel.selectedItemPosition != it) spClaudeModel.setSelection(it, false) }
            }

            val tg = snap.optString("tg_mode", "يدوي")
            tgModeItems.indexOf(tg).takeIf { it >= 0 }?.let { if (spTgMode.selectedItemPosition != it) spTgMode.setSelection(it, false) }
        } finally {
            isSyncingUi = false
        }

        val lbl = snap.optString("label", "")
        if (lbl.isNotBlank()) tvAnswerLabel.text = lbl
        tvLogContent.text = snap.optString("log", "—").ifBlank { "—" }
        tvDiagInfo.text = "القناة النشطة: ${if (channel == "local") "محلي ($discoveredLocalUrl $manualLocalUrl)" else "Firebase Firestore"}"

        val vers = snap.optJSONObject("vers")
        if (vers != null) {
            listOf("lists", "data", "file", "answer", "prompt").forEach { k ->
                val v = vers.optInt(k, 0)
                localVers[k] = v
                if (v > 0 && loadedVers[k] != v) {
                    loadedVers[k] = v
                    pullContentAsync(k, saveToDownloads = false)
                }
            }
        }
    }

    private fun sendSettingsOnly() {
        sendAction("set", collectParams(), quiet = true)
    }

    private fun sendAction(
        action: String,
        params: JSONObject = JSONObject(),
        quiet: Boolean = false,
        pullContentAfter: String? = null
    ) {
        val code = normCode(pairCode)
        if (code.length < 12) {
            if (!quiet) toast("أدخل رمز الربط أولاً من تبويب 'السجل والربط'")
            return
        }
        netExec.execute {
            try {
                val res = executeRemoteAction(code, action, params)
                val ok = res.optBoolean("ok", false)
                val err = res.optString("error", "")
                mainHandler.post {
                    if (!ok && !quiet) {
                        toast(err.ifBlank { "تعذر تنفيذ الأمر: $action" })
                    } else if (ok && !quiet && pullContentAfter == null) {
                        toast("تم إرسال الأمر: $action")
                    }
                }
                if (ok && pullContentAfter != null) {
                    Thread.sleep(650)
                    pullContentBlocking(pullContentAfter, saveToDownloads = (pullContentAfter == "file" && action == "make_file"))
                }
            } catch (e: Throwable) {
                mainHandler.post {
                    if (!quiet) toast("خطأ: ${e.message ?: e.javaClass.simpleName}")
                }
            }
        }
    }

    private fun executeRemoteAction(code: String, action: String, params: JSONObject): JSONObject {
        val loc = candidateLocalUrl()
        if ((connModeIdx == 0 && activeChannel == "local" && loc.isNotBlank()) || (connModeIdx == 1 && loc.isNotBlank())) {
            val payload = JSONObject().put("action", action).put("params", params).toString()
            val (sc, body) = httpJson("$loc/act", "POST", payload, mapOf("X-Token" to code), timeoutMs = 22000)
            if (sc == 200) return JSONObject(body)
            return JSONObject().put("ok", false).put("error", "HTTP $sc: $body")
        }

        // Firebase Firestore / RTDB command channel
        val room = code.lowercase(Locale.US)
        val cmdId = "cmd_${System.currentTimeMillis()}_${UUID.randomUUID().toString().take(6)}"
        if (isFirestoreUrl(fbUrl)) {
            val keyParam = URLEncoder.encode(fbSecret.ifBlank { DEFAULT_FB_API_KEY }, "UTF-8")
            val cmdUrl = "${firestoreBaseUrl()}/rooms/$room/items/cmd?key=$keyParam"
            val cmdBody = fsEncodeDoc(
                mapOf(
                    "kind" to "cmd",
                    "id" to cmdId,
                    "action" to action,
                    "paramsJson" to params.toString(),
                    "ts" to (System.currentTimeMillis() / 1000L)
                )
            )
            val (sc, respTxt) = httpJson(cmdUrl, "PATCH", cmdBody, timeoutMs = 8000)
            if (sc !in 200..299) return JSONObject().put("ok", false).put("error", "Firebase HTTP $sc: $respTxt")
            if (action == "set" || action == "hb") return JSONObject().put("ok", true)

            val respUrl = "${firestoreBaseUrl()}/rooms/$room/items/resp?key=$keyParam"
            val deadline = System.currentTimeMillis() + 18000L
            while (System.currentTimeMillis() < deadline) {
                Thread.sleep(600)
                val (rsc, rbody) = httpJson(respUrl, "GET", timeoutMs = 5000)
                if (rsc == 200) {
                    val doc = fsDecodeDoc(rbody)
                    if (doc.optString("id") == cmdId) {
                        return JSONObject().apply {
                            put("ok", doc.optBoolean("ok", false))
                            put("error", doc.optString("error", ""))
                            put("name", doc.optString("name", ""))
                            put("file_ver", doc.optInt("file_ver", 0))
                        }
                    }
                }
            }
            return JSONObject().put("ok", true)
        } else {
            val auth = if (fbSecret.isNotBlank()) "?auth=${URLEncoder.encode(fbSecret, "UTF-8")}" else ""
            val cmdUrl = "${fbUrl.trimEnd('/')}/rooms/$room/cmd.json$auth"
            val payload = JSONObject().put("id", cmdId).put("action", action).put("params", params).toString()
            val (sc, _) = httpJson(cmdUrl, "PUT", payload, timeoutMs = 8000)
            if (sc !in 200..299) return JSONObject().put("ok", false).put("error", "Firebase HTTP $sc")
            return JSONObject().put("ok", true)
        }
    }

    private fun pullContentAsync(key: String, saveToDownloads: Boolean) {
        netExec.execute { pullContentBlocking(key, saveToDownloads) }
    }

    private fun pullContentAndSaveFile() {
        netExec.execute {
            val ok = pullContentBlocking("file", saveToDownloads = true)
            if (!ok) {
                mainHandler.post { toast("لا يوجد ملف جاهز بعد — اضغط 'إنشاء الملف' أولاً") }
            }
        }
    }

    private fun runFetchCreateAndDownloadWorkflow() {
        val code = normCode(pairCode)
        if (code.length < 12) {
            toast("أدخل رمز الربط أولاً")
            return
        }
        mainHandler.post {
            progressBusy.visibility = View.VISIBLE
            tvStatusBar.text = "⚡ 1/3 جاري جلب البيانات الحية من MT5..."
        }
        netExec.execute {
            try {
                val r1 = executeRemoteAction(code, "fetch", collectParams())
                if (!r1.optBoolean("ok", false)) {
                    mainHandler.post { toast(r1.optString("error", "فشل جلب البيانات")) }
                    return@execute
                }
                // Wait for PC busy flag to finish fetching
                val deadline = System.currentTimeMillis() + 90000L
                Thread.sleep(1500)
                while (System.currentTimeMillis() < deadline) {
                    val s = lastSnap
                    if (s != null && !s.optBoolean("busy", false)) break
                    Thread.sleep(900)
                }
                pullContentBlocking("data", saveToDownloads = false)

                mainHandler.post { tvStatusBar.text = "📄 2/3 جاري إنشاء ملف .txt على الكمبيوتر..." }
                val r2 = executeRemoteAction(code, "make_file", collectParams())
                if (!r2.optBoolean("ok", false)) {
                    mainHandler.post { toast(r2.optString("error", "فشل إنشاء الملف")) }
                    return@execute
                }
                mainHandler.post { tvStatusBar.text = "⬇️ 3/3 جاري استلام وحفظ الملف في الهاتف..." }
                Thread.sleep(800)
                pullContentBlocking("file", saveToDownloads = true)
            } catch (e: Throwable) {
                mainHandler.post { toast("تعذر إتمام السير: ${e.message}") }
            } finally {
                mainHandler.post { progressBusy.visibility = View.GONE }
            }
        }
    }

    private fun pullContentBlocking(key: String, saveToDownloads: Boolean): Boolean {
        val code = normCode(pairCode)
        if (code.length < 12) return false
        var contentObj: JSONObject? = null
        try {
            val loc = candidateLocalUrl()
            if ((connModeIdx == 0 && activeChannel == "local" && loc.isNotBlank()) || (connModeIdx == 1 && loc.isNotBlank())) {
                val (sc, body) = httpJson("$loc/content?k=$key", "GET", headers = mapOf("X-Token" to code), timeoutMs = 10000)
                if (sc == 200) contentObj = JSONObject(body)
            }
            if (contentObj == null && (connModeIdx == 0 || connModeIdx == 2)) {
                val room = code.lowercase(Locale.US)
                if (isFirestoreUrl(fbUrl)) {
                    val keyParam = URLEncoder.encode(fbSecret.ifBlank { DEFAULT_FB_API_KEY }, "UTF-8")
                    val url = "${firestoreBaseUrl()}/rooms/$room/items/$key?key=$keyParam"
                    val (sc, body) = httpJson(url, "GET", timeoutMs = 10000)
                    if (sc == 200) contentObj = fsDecodeDoc(body)
                } else {
                    val auth = if (fbSecret.isNotBlank()) "?auth=${URLEncoder.encode(fbSecret, "UTF-8")}" else ""
                    val url = "${fbUrl.trimEnd('/')}/rooms/$room/content/$key.json$auth"
                    val (sc, body) = httpJson(url, "GET", timeoutMs = 10000)
                    if (sc == 200 && body.isNotBlank() && body != "null") contentObj = JSONObject(body)
                }
            }
        } catch (_: Throwable) {}

        val c = contentObj ?: return false
        val name = c.optString("name", "SMC_$key.txt")
        val text = c.optString("text", "")
        if (text.isBlank()) return false

        mainHandler.post {
            when (key) {
                "data" -> {
                    dataText = text
                    tvDataContent.text = text
                }
                "file" -> {
                    fileName = name
                    fileText = text
                    tvFileNameLabel.text = "الملف الحالي: $name"
                    tvFileContent.text = text
                    if (saveToDownloads) {
                        val saved = saveTextFileToDownloads(name, text)
                        toast(if (saved != null) "✅ تم استلام وحفظ الملف: Downloads/SMC/$name" else "✅ تم استلام الملف: $name")
                        tabLayout.getTabAt(3)?.select()
                    }
                }
                "answer" -> {
                    answerText = text
                    tvAnswerContent.text = text
                }
                "prompt" -> {
                    promptText = text
                    if (!etPrompt.hasFocus()) etPrompt.setText(text)
                }
                "lists" -> {
                    if (text != lastListsJson) {
                        lastListsJson = text
                        applyListsJson(text)
                    }
                }
            }
        }
        return true
    }

    private fun applyListsJson(raw: String) {
        try {
            val js = JSONObject(raw)
            isSyncingUi = true
            js.optJSONArray("symbols")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    symbolItems = list.toMutableList()
                    setSpinnerItems(spSymbol, symbolItems, lastSnap?.optString("symbol"))
                }
            }
            js.optJSONArray("providers")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    providerItems = list.toMutableList()
                    setSpinnerItems(spProvider, providerItems, lastSnap?.optString("provider"))
                }
            }
            js.optJSONArray("gem_models")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    gemModelItems = list.toMutableList()
                    setSpinnerItems(spGemModel, gemModelItems, lastSnap?.optString("gem_model"))
                }
            }
            js.optJSONArray("claude_models")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    claudeModelItems = list.toMutableList()
                    setSpinnerItems(spClaudeModel, claudeModelItems, lastSnap?.optString("claude_model"))
                }
            }
            js.optJSONArray("tg_modes")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    tgModeItems = list.toMutableList()
                    setSpinnerItems(spTgMode, tgModeItems, lastSnap?.optString("tg_mode"))
                }
            }
            js.optJSONArray("presets")?.let { arr ->
                val list = jsonToList(arr)
                if (list.isNotEmpty()) {
                    presetItems = list.toMutableList()
                    setSpinnerItems(spPreset, listOf("اختر أمراً جاهزاً...") + presetItems)
                }
            }
        } catch (_: Throwable) {
        } finally {
            isSyncingUi = false
        }
    }

    private fun jsonToList(arr: JSONArray): List<String> {
        val out = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val s = arr.optString(i, "")
            if (s.isNotBlank()) out.add(s)
        }
        return out
    }

    // ==========================================================
    // File Storage & Sharing
    // ==========================================================
    private fun saveTextFileToDownloads(name: String, content: String): Uri? {
        return try {
            val safeName = name.ifBlank { "SMC_file.txt" }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val cv = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, safeName)
                    put(MediaStore.Downloads.MIME_TYPE, "text/plain")
                    put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/SMC")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv)
                if (uri != null) {
                    contentResolver.openOutputStream(uri)?.use { it.write(content.toByteArray(Charsets.UTF_8)) }
                }
                uri
            } else {
                val baseDir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
                val dir = File(baseDir, "SMC").apply { mkdirs() }
                val f = File(dir, safeName)
                f.writeText(content, Charsets.UTF_8)
                Uri.fromFile(f)
            }
        } catch (_: Throwable) {
            null
        }
    }

    private fun shareFileText() {
        if (fileText.isBlank()) {
            toast("لا يوجد ملف لمشاركته — استلم الملف أولاً")
            return
        }
        val uri = saveTextFileToDownloads(fileName, fileText)
        if (uri != null && uri.scheme == "content") {
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_SUBJECT, fileName)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(intent, "مشاركة ملف SMC"))
        } else {
            sharePlainText(fileText, fileName)
        }
    }

    private fun sharePlainText(text: String, subject: String) {
        if (text.isBlank()) {
            toast("لا يوجد نص للمشاركة")
            return
        }
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_SUBJECT, subject)
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(intent, "مشاركة"))
    }

    private fun copyText(label: String, text: String) {
        if (text.isBlank()) {
            toast("لا يوجد محتوى لنسخه")
            return
        }
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText(label, text))
        toast("تم نسخ $label")
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
