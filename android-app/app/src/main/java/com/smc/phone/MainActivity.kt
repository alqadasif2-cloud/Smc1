package com.smc.phone

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Typeface
import android.media.AudioManager
import android.media.ToneGenerator
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
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewConfiguration
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class MainActivity : AppCompatActivity() {

    companion object {
        // Default Firebase Firestore configuration (shared database wired to PC & Web)
        private const val DEFAULT_FB_PROJECT_ID = "gen-lang-client-0819396986"
        private const val DEFAULT_FB_DATABASE_ID = "ai-studio-remotecontrolsyn-df2f1204-af22-4100-8861-97c8a605fa68"
        private const val DEFAULT_FB_API_KEY = "AIzaSyCtdkKUAcEa5pZjKxxk1t9HayIq_Pi-ehw"
        private const val DEFAULT_FB_URL = "firestore://$DEFAULT_FB_PROJECT_ID/$DEFAULT_FB_DATABASE_ID"
        private const val DEFAULT_PAIR_CODE = "SMC-AUTO-BRIDGE"
        private const val DEFAULT_INTERNAL_AI_URL = "https://ais-pre-5as3ie4knpzuvhxk3weepk-38839718891.europe-west3.run.app/api/gemini/analyze"

        private const val BRIDGE_UDP_PORT = 8766
        private const val CHART_REFRESH_SEC = 60
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

        // Modern dark trading terminal palette
        private const val COL_BG = "#0B1120"
        private const val COL_HEADER = "#0F172A"
        private const val COL_CARD = "#111827"
        private const val COL_SURFACE = "#1E293B"
        private const val COL_BORDER = "#334155"
        private const val COL_TEXT_PRIMARY = "#F8FAFC"
        private const val COL_TEXT_SECONDARY = "#94A3B8"
        private const val COL_ACCENT_CYAN = "#38BDF8"
    }

    data class CandleBar(
        val timeSec: Long,
        val open: Double,
        val high: Double,
        val low: Double,
        val close: Double,
        val vol: Long
    )

    private val mainHandler = Handler(Looper.getMainLooper())
    private val netExec = Executors.newCachedThreadPool()

    // Connection & Feedback settings
    private var pairCode = DEFAULT_PAIR_CODE
    private var connModeIdx = 0 // 0=Auto, 1=Local, 2=Firebase
    private var fbUrl = DEFAULT_FB_URL
    private var fbSecret = DEFAULT_FB_API_KEY
    private var manualLocalUrl = ""
    private var internalAiUrl = DEFAULT_INTERNAL_AI_URL
    private var discoveredLocalUrl = ""
    private var activeChannel = "none" // "local" | "firebase" | "none"
    private var lastLocalScanMs = 0L
    private var pollingActive = false
    private var isSyncingUi = false
    private var soundEnabled = true

    // Latest synced state & contents
    private var lastSnap: JSONObject? = null
    private var lastBusyState = false
    private var pendingAsyncTask: String? = null
    private val localVers = mutableMapOf<String, Int>()
    private val loadedVers = mutableMapOf<String, Int>()
    private var dataText = ""
    private var fileText = ""
    private var fileName = "SMC_request.txt"
    private var answerText = ""
    private var promptText = ""
    private var lastListsJson = ""
    private var lastAnswerTs = 0L
    private var pollTickCounter = 0
    @Volatile private var waitingForInternalGemini = false
    @Volatile private var latestPulledDataText = ""
    @Volatile private var latestPulledFileText = ""

    // Chart streaming state
    private var chartStreaming = false
    private var chartCountdownSec = CHART_REFRESH_SEC
    private var selectedChartTf = "M15"
    private var chartSymbol = "XAUUSD"
    private var chartDigits = 2
    private var chartBid = 0.0
    private var chartAsk = 0.0
    private var chartUpdatedAt = ""
    private var chartBars = emptyList<CandleBar>()

    private var symbolItems = mutableListOf("XAUUSD")
    private var providerItems = DEFAULT_PROVIDERS.toMutableList()
    private var gemModelItems = DEFAULT_GEM_MODELS.toMutableList()
    private var claudeModelItems = DEFAULT_CLAUDE_MODELS.toMutableList()
    private var tgModeItems = DEFAULT_TG_MODES.toMutableList()
    private var presetItems = mutableListOf<String>()

    // Header / Feedback / Status Views
    private lateinit var tvPcHeader: TextView
    private lateinit var tvChannelBadge: TextView
    private lateinit var tvMt5Status: TextView
    private lateinit var tvLivePrice: TextView
    private lateinit var tvStatusBar: TextView
    private lateinit var progressBusy: ProgressBar
    private lateinit var btnSoundToggle: MaterialButton
    private lateinit var cardFeedback: MaterialCardView
    private lateinit var tvFeedbackTitle: TextView
    private lateinit var tvFeedbackSub: TextView
    private lateinit var tabLayout: TabLayout
    private val tabContainers = mutableListOf<View>()

    // Tab 0: Control views
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
    private lateinit var btnMakeFileInternalGemini: MaterialButton
    private lateinit var btnAnalyzeInternalGemini: MaterialButton
    private lateinit var btnOpenChartQuick: MaterialButton
    private lateinit var btnAi: MaterialButton
    private lateinit var btnFetchAi: MaterialButton
    private lateinit var btnTgAnswer: MaterialButton
    private lateinit var btnTgFile: MaterialButton
    private lateinit var btnModels: MaterialButton
    private lateinit var btnSavePc: MaterialButton
    private lateinit var btnStop: MaterialButton

    // Tab 1: Live Chart views
    private lateinit var btnChartStart: MaterialButton
    private lateinit var btnChartStop: MaterialButton
    private lateinit var tvChartTimer: TextView
    private lateinit var tvChartHud: TextView
    private lateinit var chartView: CandleChartView
    private val chartTfButtons = mutableMapOf<String, MaterialButton>()

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
    private lateinit var etInternalAiUrl: EditText
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

    private val chartTickRunnable = object : Runnable {
        override fun run() {
            if (!chartStreaming) return
            chartCountdownSec -= 1
            if (chartCountdownSec <= 0) {
                chartCountdownSec = CHART_REFRESH_SEC
                tvChartTimer.text = "⏱ جاري تحديث الشموع من الكمبيوتر..."
                refreshChartFromPc(silent = true)
            } else {
                tvChartTimer.text = "🟢 بث مباشر • التحديث التلقائي كل 1 دقيقة (المتبقي: ${chartCountdownSec}ث)"
            }
            mainHandler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.parseColor(COL_HEADER)
        window.navigationBarColor = Color.parseColor(COL_BG)
        loadPrefs()
        buildUi()
        applyPrefsToSettingsUi()
        updateChartControlsUi()
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
        chartStreaming = false
        mainHandler.removeCallbacks(chartTickRunnable)
        mainHandler.removeCallbacks(pollRunnable)
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
        internalAiUrl = p.getString("internal_ai_url", DEFAULT_INTERNAL_AI_URL)?.ifBlank { DEFAULT_INTERNAL_AI_URL } ?: DEFAULT_INTERNAL_AI_URL
        soundEnabled = p.getBoolean("sound_enabled", true)
        val savedTf = p.getString("chart_tf", "M15") ?: "M15"
        if (TF_NAMES.contains(savedTf)) selectedChartTf = savedTf
    }

    private fun savePrefs() {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putString("pair_code", pairCode)
            .putInt("conn_mode", connModeIdx)
            .putString("fb_url", fbUrl)
            .putString("fb_secret", fbSecret)
            .putString("manual_local", manualLocalUrl)
            .putString("internal_ai_url", internalAiUrl)
            .putBoolean("sound_enabled", soundEnabled)
            .putString("chart_tf", selectedChartTf)
            .apply()
    }

    private fun normCode(c: String?): String {
        return (c ?: "").replace(Regex("[^A-Za-z0-9]"), "").uppercase(Locale.US)
    }

    // ==========================================================
    // Visual + Audio Action Completion Feedback
    // ==========================================================
    private fun notifyActionCompleted(success: Boolean, title: String, detail: String = "") {
        val nowTime = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        mainHandler.post {
            cardFeedback.visibility = View.VISIBLE
            if (success) {
                cardFeedback.setCardBackgroundColor(Color.parseColor("#064E3B"))
                cardFeedback.strokeColor = Color.parseColor("#10B981")
                tvFeedbackTitle.setTextColor(Color.parseColor("#A7F3D0"))
                tvFeedbackTitle.text = "✅ $title"
                tvFeedbackSub.setTextColor(Color.parseColor("#D1FAE5"))
            } else {
                cardFeedback.setCardBackgroundColor(Color.parseColor("#7F1D1D"))
                cardFeedback.strokeColor = Color.parseColor("#EF4444")
                tvFeedbackTitle.setTextColor(Color.parseColor("#FECACA"))
                tvFeedbackTitle.text = "❌ $title"
                tvFeedbackSub.setTextColor(Color.parseColor("#FEE2E2"))
            }
            tvFeedbackSub.text = if (detail.isNotBlank()) "$detail  •  $nowTime" else "وقت الإنجاز: $nowTime"
            tvStatusBar.text = if (success) "✅ $title" else "❌ $title"

            cardFeedback.alpha = 0.5f
            cardFeedback.scaleX = 0.98f
            cardFeedback.scaleY = 0.98f
            cardFeedback.animate()
                .alpha(1f)
                .scaleX(1f)
                .scaleY(1f)
                .setDuration(260)
                .start()
        }
        if (soundEnabled) {
            playFeedbackTone(success)
        }
    }

    private fun playFeedbackTone(success: Boolean) {
        netExec.execute {
            var tg: ToneGenerator? = null
            try {
                tg = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 90)
                if (success) {
                    tg.startTone(ToneGenerator.TONE_PROP_ACK, 220)
                } else {
                    tg.startTone(ToneGenerator.TONE_PROP_NACK, 280)
                }
                Thread.sleep(320)
            } catch (_: Throwable) {
            } finally {
                try {
                    tg?.release()
                } catch (_: Throwable) {
                }
            }
        }
    }

    // ==========================================================
    // UI Construction (Modern Dark Trading Terminal, RTL)
    // ==========================================================
    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            setBackgroundColor(Color.parseColor(COL_BG))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // Top Header Surface
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor(COL_HEADER))
            setPadding(dp(14), dp(12), dp(14), dp(10))
        }

        val topRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        tvPcHeader = TextView(this).apply {
            text = "SMC Phone Pro"
            setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        tvChannelBadge = TextView(this).apply {
            text = "جاري الربط..."
            setTextColor(Color.parseColor("#38BDF8"))
            textSize = 11f
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(8), 0, dp(8), 0)
        }
        btnSoundToggle = MaterialButton(this).apply {
            text = if (soundEnabled) "🔊" else "🔇"
            setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
            setBackgroundColor(Color.parseColor(COL_SURFACE))
            cornerRadius = dp(8)
            minWidth = 0
            minimumWidth = 0
            minHeight = 0
            minimumHeight = 0
            setPadding(dp(10), dp(4), dp(10), dp(4))
            textSize = 13f
            setOnClickListener {
                soundEnabled = !soundEnabled
                savePrefs()
                text = if (soundEnabled) "🔊" else "🔇"
                toast(if (soundEnabled) "تم تفعيل التنبيه الصوتي" else "تم كتم التنبيه الصوتي")
                if (soundEnabled) playFeedbackTone(true)
            }
        }
        topRow.addView(tvPcHeader)
        topRow.addView(tvChannelBadge)
        topRow.addView(btnSoundToggle)
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
            setTextColor(Color.parseColor(COL_ACCENT_CYAN))
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
            text = "متصل تلقائياً عبر الشبكة المحلية أو Firebase"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
        }
        barRow.addView(progressBusy)
        barRow.addView(tvStatusBar)
        header.addView(barRow)

        // Prominent Visual Completion Banner (updates + sound on every action)
        cardFeedback = MaterialCardView(this).apply {
            visibility = View.GONE
            radius = dp(10).toFloat()
            cardElevation = dp(2).toFloat()
            strokeWidth = dp(1)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, dp(8), 0, 0) }
            setOnClickListener { visibility = View.GONE }
        }
        val fbInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(8), dp(12), dp(8))
        }
        tvFeedbackTitle = TextView(this).apply {
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
        }
        tvFeedbackSub = TextView(this).apply {
            textSize = 11f
            setPadding(0, dp(2), 0, 0)
        }
        fbInner.addView(tvFeedbackTitle)
        fbInner.addView(tvFeedbackSub)
        cardFeedback.addView(fbInner)
        header.addView(cardFeedback)

        root.addView(header)

        // Hairline Divider
        root.addView(View(this).apply {
            setBackgroundColor(Color.parseColor("#1E293B"))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1))
        })

        // Modern Dark Tabs
        tabLayout = TabLayout(this).apply {
            tabMode = TabLayout.MODE_SCROLLABLE
            setBackgroundColor(Color.parseColor(COL_HEADER))
            setSelectedTabIndicatorColor(Color.parseColor(COL_ACCENT_CYAN))
            setSelectedTabIndicatorHeight(dp(3))
            setTabTextColors(Color.parseColor("#94A3B8"), Color.parseColor("#F8FAFC"))
        }
        val tabTitles = listOf("التحكم", "📈 الرسم البياني", "الأوامر", "البيانات", "الملف txt", "التحليل", "السجل والربط")
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

        val t0 = buildControlTab()
        val t1 = buildChartTab()
        val t2 = buildPromptsTab()
        val t3 = buildDataTab()
        val t4 = buildFileTab()
        val t5 = buildAnswerTab()
        val t6 = buildLogBridgeTab()
        tabContainers.addAll(listOf(t0, t1, t2, t3, t4, t5, t6))
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
                if (tab.position == 1 && chartBars.isEmpty() && lastSnap?.optBoolean("chart_active", false) == true) {
                    pullContentAsync("chart", saveToDownloads = false)
                }
            }
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })

        setContentView(root)
    }

    private fun card(parent: LinearLayout, title: String): LinearLayout {
        val c = MaterialCardView(this).apply {
            radius = dp(14).toFloat()
            cardElevation = dp(2).toFloat()
            setCardBackgroundColor(Color.parseColor(COL_CARD))
            strokeColor = Color.parseColor("#1E293B")
            strokeWidth = dp(1)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, dp(12)) }
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(14))
        }
        if (title.isNotEmpty()) {
            inner.addView(TextView(this).apply {
                text = title
                setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
                textSize = 14f
                setTypeface(typeface, Typeface.BOLD)
                setPadding(0, 0, 0, dp(10))
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
            cornerRadius = dp(10)
            textSize = 13f
            isAllCaps = false
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, dp(4), 0, dp(4)) }
        }
    }

    private fun styleEditText(et: EditText): EditText {
        return et.apply {
            setBackgroundColor(Color.parseColor(COL_SURFACE))
            setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
            setHintTextColor(Color.parseColor("#64748B"))
            setPadding(dp(12), dp(10), dp(12), dp(10))
            textSize = 13f
        }
    }

    private fun labelRow(parent: LinearLayout, label: String): Spinner {
        parent.addView(TextView(this).apply {
            text = label
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(6), 0, dp(4))
        })
        val sp = Spinner(this).apply {
            setBackgroundColor(Color.parseColor(COL_SURFACE))
            setPadding(dp(8), dp(6), dp(8), dp(6))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { setMargins(0, 0, 0, dp(8)) }
        }
        parent.addView(sp)
        return sp
    }

    private fun setSpinnerItems(sp: Spinner, items: List<String>, selected: String? = null) {
        val adapter = object : ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, items) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getView(position, convertView, parent) as TextView
                v.setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
                v.textSize = 13f
                v.setPadding(dp(8), dp(6), dp(8), dp(6))
                return v
            }

            override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getDropDownView(position, convertView, parent) as TextView
                v.setBackgroundColor(Color.parseColor(COL_SURFACE))
                v.setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
                v.textSize = 14f
                v.setPadding(dp(12), dp(10), dp(12), dp(10))
                return v
            }
        }
        sp.adapter = adapter
        if (!selected.isNullOrBlank()) {
            val idx = items.indexOf(selected)
            if (idx >= 0) sp.setSelection(idx, false)
        }
    }

    // ---------- Tab 0: Control ----------
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
        btnConnect = makeBtn("🔌 اتصال / إعادة اتصال MT5", "#0284C7") {
            pendingAsyncTask = "connect"
            sendAction("connect")
        }
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
        val tintList = ColorStateList.valueOf(Color.parseColor(COL_ACCENT_CYAN))
        TF_NAMES.forEach { tf ->
            val cb = CheckBox(this).apply {
                text = tf
                setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
                buttonTintList = tintList
                isChecked = (tf != "D1")
                setPadding(dp(4), 0, dp(10), 0)
                setOnCheckedChangeListener { _, _ -> if (!isSyncingUi) sendSettingsOnly() }
            }
            tfChecks[tf] = cb
            tfRow.addView(cb)
        }
        tfWrap.addView(tfRow)
        c2.addView(tfWrap)

        cbChain = CheckBox(this).apply {
            text = "تحليل تلقائياً بعد الجلب"
            setTextColor(Color.parseColor(COL_TEXT_PRIMARY))
            buttonTintList = tintList
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

        btnModels = makeBtn("🔄 تحديث قوائم الموديلات", "#334155") {
            sendAction("models", completionLabel = "تحديث قوائم الموديلات")
        }
        c3.addView(btnModels)

        // Card 4: Action Buttons
        val c4 = card(box, "4) أزرار التنفيذ والرسم البياني وإرسال الملفات")
        btnOpenChartQuick = makeBtn("📈 فتح الرسم البياني المباشر (تحديث كل 1د)", "#0EA5E9") {
            tabLayout.getTabAt(1)?.select()
            startChartStreaming()
        }
        btnFetch = makeBtn("📥 جلب البيانات الحية", "#0369A1") {
            pendingAsyncTask = "fetch"
            sendAction("fetch", collectParams(), pullContentAfter = "data")
        }
        btnMakeFile = makeBtn("📄 إنشاء الملف فقط (.txt)", "#2563EB") {
            sendAction("make_file", collectParams(), pullContentAfter = "file", completionLabel = "إنشاء ملف الطلب (.txt)")
        }
        btnReceiveFile = makeBtn("⬇️ استلام الملف إلى الهاتف وحفظه", "#059669") {
            pullContentAndSaveFile()
        }
        btnWorkflowDownload = makeBtn("⚡ جلب + إنشاء ملف + استلام للهاتف", "#0D9488") {
            runFetchCreateAndDownloadWorkflow()
        }
        btnMakeFileInternalGemini = makeBtn("✨ إنشاء ملف ومشاركته مع جيمناي الداخلي", "#10B981") {
            runInternalGeminiWorkflow(createFileFirst = true)
        }
        btnAnalyzeInternalGemini = makeBtn("🤖 تحليل الملف الحالي بجيمناي الداخلي", "#0F766E") {
            runInternalGeminiWorkflow(createFileFirst = false)
        }
        btnAi = makeBtn("🤖 إنشاء الملف وإرساله للمزوّد", "#4F46E5") {
            pendingAsyncTask = "ai"
            sendAction("ai", collectParams(), pullContentAfter = "answer")
        }
        btnFetchAi = makeBtn("⚡ جلب + تحليل", "#7C3AED") {
            pendingAsyncTask = "fetch_ai"
            sendAction("fetch_ai", collectParams(), pullContentAfter = "answer")
        }
        btnTgAnswer = makeBtn("📨 إرسال النتيجة إلى Telegram", "#0284C7") {
            sendAction("tg_answer", completionLabel = "إرسال النتيجة إلى Telegram")
        }
        btnTgFile = makeBtn("📎 إنشاء ملف وإرساله إلى Telegram", "#0E7490") {
            sendAction("tg_file", completionLabel = "إرسال الملف إلى Telegram")
        }
        btnSavePc = makeBtn("💾 حفظ الإعدادات على الكمبيوتر", "#334155") {
            sendAction("save", completionLabel = "حفظ الإعدادات على الكمبيوتر")
        }
        btnStop = makeBtn("⏹ إيقاف العملية الحالية", "#DC2626") {
            pendingAsyncTask = null
            waitingForInternalGemini = false
            sendAction("stop", completionLabel = "إيقاف العملية الحالية")
        }

        listOf(
            btnOpenChartQuick, btnFetch, btnMakeFile, btnReceiveFile, btnWorkflowDownload,
            btnMakeFileInternalGemini, btnAnalyzeInternalGemini,
            btnAi, btnFetchAi, btnTgAnswer, btnTgFile, btnSavePc, btnStop
        ).forEach { c4.addView(it) }

        scroll.addView(box)
        return scroll
    }

    // ---------- Tab 1: Live Interactive Candlestick Chart ----------
    private fun buildChartTab(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(10), dp(10), dp(10))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }

        // Start / Stop streaming row
        val ctrlRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        btnChartStart = makeBtn("📈 عرض الرسم البياني", "#059669") {
            startChartStreaming()
        }
        btnChartStop = makeBtn("⏹ إيقاف عرض الرسم البياني", "#DC2626") {
            stopChartStreaming()
        }
        listOf(btnChartStart, btnChartStop).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            ctrlRow.addView(b)
        }
        root.addView(ctrlRow)

        // All Timeframes Switcher (M1..D1)
        val tfScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(0, 0, 0, dp(6))
            }
        }
        val tfRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        TF_NAMES.forEach { tf ->
            val b = MaterialButton(this).apply {
                text = tf
                textSize = 12f
                isAllCaps = false
                cornerRadius = dp(8)
                minWidth = 0
                minimumWidth = 0
                setPadding(dp(12), dp(6), dp(12), dp(6))
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    setMargins(dp(3), 0, dp(3), 0)
                }
                setOnClickListener { switchChartTimeframe(tf) }
            }
            chartTfButtons[tf] = b
            tfRow.addView(b)
        }
        tfScroll.addView(tfRow)
        root.addView(tfScroll)

        // Zoom + Manual Refresh Row
        val zoomRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bZoomIn = makeBtn("🔍+", COL_SURFACE) { chartView.zoomBy(1.25f) }
        val bZoomOut = makeBtn("🔍-", COL_SURFACE) { chartView.zoomBy(0.8f) }
        val bReset = makeBtn("↺ أحدث شمعة", COL_SURFACE) { chartView.resetView() }
        val bRefreshNow = makeBtn("🔄 تحديث الآن", "#0284C7") {
            if (!chartStreaming) {
                startChartStreaming()
            } else {
                chartCountdownSec = CHART_REFRESH_SEC
                refreshChartFromPc(silent = false)
            }
        }
        listOf(bZoomIn, bZoomOut, bReset, bRefreshNow).forEach { b ->
            b.textSize = 11f
            b.setPadding(dp(6), dp(6), dp(6), dp(6))
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(2), 0, dp(2), dp(6))
            }
            zoomRow.addView(b)
        }
        root.addView(zoomRow)

        // Timer & Status Bar
        tvChartTimer = TextView(this).apply {
            text = "⏹ البث متوقف — اضغط 'عرض الرسم البياني' للنقل من الكمبيوتر"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 11f
            setPadding(dp(4), 0, dp(4), dp(4))
        }
        root.addView(tvChartTimer)

        // OHLCV HUD Bar
        tvChartHud = TextView(this).apply {
            text = "اسحب للتحريك، قرّب بإصبعين للتكبير، وانقر على أي شمعة لمعاينة تفاصيلها"
            setBackgroundColor(Color.parseColor(COL_CARD))
            setTextColor(Color.parseColor(COL_ACCENT_CYAN))
            typeface = Typeface.MONOSPACE
            textSize = 11f
            setPadding(dp(10), dp(7), dp(10), dp(7))
        }
        root.addView(tvChartHud)

        // Interactive Candlestick Canvas
        val chartCard = MaterialCardView(this).apply {
            radius = dp(12).toFloat()
            strokeColor = Color.parseColor("#1E293B")
            strokeWidth = dp(1)
            setCardBackgroundColor(Color.parseColor(COL_BG))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f).apply {
                setMargins(0, dp(6), 0, 0)
            }
        }
        chartView = CandleChartView(this) { bar, isHover ->
            val d = chartDigits.coerceIn(0, 6)
            val fmt = "%.${d}f"
            val tStr = formatUnixTime(bar.timeSec, selectedChartTf)
            val tag = if (isHover) "📍" else "●"
            tvChartHud.text = "$tag $chartSymbol ($selectedChartTf) $tStr | O:${String.format(Locale.US, fmt, bar.open)} H:${String.format(Locale.US, fmt, bar.high)} L:${String.format(Locale.US, fmt, bar.low)} C:${String.format(Locale.US, fmt, bar.close)} V:${bar.vol}"
        }
        chartCard.addView(chartView)
        root.addView(chartCard)

        return root
    }

    private fun startChartStreaming() {
        chartStreaming = true
        chartCountdownSec = CHART_REFRESH_SEC
        mainHandler.removeCallbacks(chartTickRunnable)
        mainHandler.postDelayed(chartTickRunnable, 1000)
        updateChartControlsUi()
        tvChartTimer.text = "🟢 جاري جلب الرسم البياني ($selectedChartTf) من الكمبيوتر..."
        sendAction(
            action = "chart_start",
            params = JSONObject().put("tf", selectedChartTf),
            pullContentAfter = "chart",
            completionLabel = "تشغيل الرسم البياني المباشر ($selectedChartTf)"
        )
    }

    private fun stopChartStreaming() {
        chartStreaming = false
        mainHandler.removeCallbacks(chartTickRunnable)
        updateChartControlsUi()
        tvChartTimer.text = "⏹ تم إيقاف عرض الرسم البياني — لا يتم نقل أي بيانات (توفير الاستهلاك)"
        sendAction(
            action = "chart_stop",
            completionLabel = "إيقاف عرض الرسم البياني وتوفير الاستهلاك"
        )
    }

    private fun switchChartTimeframe(tf: String) {
        if (!TF_NAMES.contains(tf)) return
        selectedChartTf = tf
        savePrefs()
        updateChartControlsUi()
        if (chartStreaming) {
            chartCountdownSec = CHART_REFRESH_SEC
            sendAction(
                action = "chart_tf",
                params = JSONObject().put("tf", tf),
                pullContentAfter = "chart",
                completionLabel = "تغيير فريم الرسم البياني إلى $tf"
            )
        } else {
            startChartStreaming()
        }
    }

    private fun refreshChartFromPc(silent: Boolean) {
        sendAction(
            action = "chart_refresh",
            params = JSONObject().put("tf", selectedChartTf),
            quiet = silent,
            pullContentAfter = "chart",
            completionLabel = if (silent) null else "تحديث الرسم البياني ($selectedChartTf)"
        )
    }

    private fun updateChartControlsUi() {
        if (!::btnChartStart.isInitialized) return
        btnChartStart.isEnabled = !chartStreaming
        btnChartStart.alpha = if (chartStreaming) 0.55f else 1f
        btnChartStop.isEnabled = chartStreaming
        btnChartStop.alpha = if (chartStreaming) 1f else 0.55f

        chartTfButtons.forEach { (tf, btn) ->
            val active = (tf == selectedChartTf)
            btn.setBackgroundColor(Color.parseColor(if (active) "#0284C7" else COL_SURFACE))
            btn.setTextColor(Color.parseColor(if (active) "#FFFFFF" else COL_TEXT_SECONDARY))
        }
        if (chartStreaming) {
            tvChartTimer.text = "🟢 بث مباشر • التحديث التلقائي كل 1 دقيقة (المتبقي: ${chartCountdownSec}ث)"
        }
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
        val bAdd = makeBtn("➕ إضافة", "#334155") {
            val p = spPreset.selectedItem?.toString() ?: ""
            if (p.isNotBlank() && !p.startsWith("اختر")) {
                val cur = etPrompt.text.toString().trimEnd()
                etPrompt.setText(if (cur.isEmpty()) p else "$cur\n$p")
                notifyActionCompleted(true, "تمت إضافة الأمر الجاهز")
            }
        }
        val bSavePrompt = makeBtn("💾 حفظ الأوامر", "#059669") {
            sendAction("set_prompt", JSONObject().put("text", etPrompt.text.toString()), completionLabel = "حفظ الأوامر الافتراضية")
        }
        val bResetPrompt = makeBtn("↩ استعادة", "#475569") {
            sendAction("reset_prompt", pullContentAfter = "prompt", completionLabel = "استعادة الأوامر الأصلية")
        }
        listOf(bAdd, bSavePrompt, bResetPrompt).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            rowBtns.addView(b)
        }
        box.addView(rowBtns)

        etPrompt = styleEditText(EditText(this)).apply {
            gravity = Gravity.TOP or Gravity.START
            textAlignment = View.TEXT_ALIGNMENT_VIEW_START
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
            pendingAsyncTask = "fetch"
            sendAction("fetch", collectParams(), pullContentAfter = "data")
        }
        val b2 = makeBtn("🔄 سحب أحدث بيانات", "#334155") {
            pullContentAsync("data", saveToDownloads = false, notifyLabel = "تحديث عرض البيانات الحية")
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
            setBackgroundColor(Color.parseColor(COL_CARD))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvDataContent = TextView(this).apply {
            text = "لا توجد بيانات مجلوبة بعد — اضغط 'جلب البيانات الحية'."
            setTextColor(Color.parseColor("#E2E8F0"))
            setPadding(dp(12), dp(12), dp(12), dp(12))
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
            setTextColor(Color.parseColor(COL_ACCENT_CYAN))
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        box.addView(tvFileNameLabel)

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bCreate = makeBtn("📄 إنشاء الملف", "#2563EB") {
            sendAction("make_file", collectParams(), pullContentAfter = "file", completionLabel = "إنشاء ملف الطلب (.txt)")
        }
        val bPullSave = makeBtn("⬇️ استلام وحفظ للهاتف", "#059669") {
            pullContentAndSaveFile()
        }
        val bShare = makeBtn("📤 مشاركة", "#334155") {
            shareFileText()
        }
        listOf(bCreate, bPullSave, bShare).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            row.addView(b)
        }
        box.addView(row)
        box.addView(makeBtn("✨ إنشاء ملف ومشاركته مع جيمناي الداخلي", "#10B981") {
            runInternalGeminiWorkflow(createFileFirst = true)
        })

        val sc = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor(COL_CARD))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvFileContent = TextView(this).apply {
            text = "لم يتم إنشاء أو استلام ملف بعد."
            setTextColor(Color.parseColor("#E2E8F0"))
            setPadding(dp(12), dp(12), dp(12), dp(12))
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
            setTextColor(Color.parseColor(COL_ACCENT_CYAN))
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(6))
        }
        box.addView(tvAnswerLabel)

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val bCopy = makeBtn("📋 نسخ النتيجة", "#334155") { copyText("النتيجة", answerText) }
        val bTg = makeBtn("📨 إرسال لـ Telegram", "#0284C7") {
            sendAction("tg_answer", completionLabel = "إرسال النتيجة إلى Telegram")
        }
        val bShare = makeBtn("📤 مشاركة", "#0F766E") { sharePlainText(answerText, "نتيجة تحليل SMC") }
        listOf(bCopy, bTg, bShare).forEach { b ->
            b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(dp(3), 0, dp(3), dp(6))
            }
            row.addView(b)
        }
        box.addView(row)
        box.addView(makeBtn("✨ إنشاء ملف ومشاركته مع جيمناي الداخلي الآن", "#10B981") {
            runInternalGeminiWorkflow(createFileFirst = true)
        })

        val sc = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor(COL_CARD))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        tvAnswerContent = TextView(this).apply {
            text = "لا توجد نتيجة تحليل بعد."
            setTextColor(Color.parseColor("#F1F5F9"))
            setPadding(dp(12), dp(12), dp(12), dp(12))
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
        cConn.addView(TextView(this).apply {
            text = "رمز الربط (مشترك تلقائياً بدون إدخال يدوي)"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, 0, 0, dp(4))
        })
        etPairCode = styleEditText(EditText(this)).apply {
            hint = DEFAULT_PAIR_CODE
            isSingleLine = true
        }
        cConn.addView(etPairCode)

        spConnMode = labelRow(cConn, "طريقة الاتصال")
        setSpinnerItems(spConnMode, MODE_LABELS, MODE_LABELS[connModeIdx])

        cConn.addView(TextView(this).apply {
            text = "عنوان المحلي اليدوي (اختياري، مثال: http://192.168.1.10:8765)"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(6), 0, dp(4))
        })
        etManualLocal = styleEditText(EditText(this)).apply {
            hint = "http://192.168.1.x:8765"
            isSingleLine = true
        }
        cConn.addView(etManualLocal)

        cConn.addView(TextView(this).apply {
            text = "رابط Firebase (مربوط افتراضياً)"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(6), 0, dp(4))
        })
        etFbUrl = styleEditText(EditText(this)).apply { isSingleLine = true }
        cConn.addView(etFbUrl)

        cConn.addView(TextView(this).apply {
            text = "مفتاح Firebase API Key / Secret"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(6), 0, dp(4))
        })
        etFbSecret = styleEditText(EditText(this)).apply {
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        cConn.addView(etFbSecret)

        cConn.addView(TextView(this).apply {
            text = "رابط جيمناي الداخلي (مربوط تلقائياً بالسيرفر)"
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(6), 0, dp(4))
        })
        etInternalAiUrl = styleEditText(EditText(this)).apply {
            hint = DEFAULT_INTERNAL_AI_URL
            isSingleLine = true
        }
        cConn.addView(etInternalAiUrl)

        cConn.addView(makeBtn("💾 حفظ الإعدادات وتطبيق الربط", "#059669") {
            pairCode = etPairCode.text.toString().trim().uppercase(Locale.US).ifBlank { DEFAULT_PAIR_CODE }
            connModeIdx = spConnMode.selectedItemPosition.coerceIn(0, 2)
            manualLocalUrl = etManualLocal.text.toString().trim().trimEnd('/')
            internalAiUrl = etInternalAiUrl.text.toString().trim().ifBlank { DEFAULT_INTERNAL_AI_URL }
            fbUrl = etFbUrl.text.toString().trim().ifBlank { DEFAULT_FB_URL }
            fbSecret = etFbSecret.text.toString().trim().ifBlank { DEFAULT_FB_API_KEY }
            savePrefs()
            notifyActionCompleted(true, "تم حفظ إعدادات الربط وتطبيقها")
            if (connModeIdx != 2) scanLocalNetworkAsync(silent = false)
            pollOnce()
        })

        cConn.addView(makeBtn("🔍 مسح الشبكة المحلية (Wi-Fi) الآن", "#0284C7") {
            scanLocalNetworkAsync(silent = false)
        })

        cConn.addView(makeBtn("↩ استعادة إعدادات Firebase الافتراضية", "#334155") {
            pairCode = DEFAULT_PAIR_CODE
            fbUrl = DEFAULT_FB_URL
            fbSecret = DEFAULT_FB_API_KEY
            internalAiUrl = DEFAULT_INTERNAL_AI_URL
            connModeIdx = 0
            savePrefs()
            applyPrefsToSettingsUi()
            notifyActionCompleted(true, "تمت استعادة إعدادات Firebase الافتراضية")
        })

        tvDiagInfo = TextView(this).apply {
            text = "الحالة: في انتظار الاتصال..."
            setTextColor(Color.parseColor(COL_TEXT_SECONDARY))
            textSize = 12f
            setPadding(0, dp(8), 0, 0)
        }
        cConn.addView(tvDiagInfo)

        val cLog = card(box, "سجل الكمبيوتر المباشر")
        tvLogContent = TextView(this).apply {
            text = "—"
            setTextColor(Color.parseColor("#CBD5E1"))
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
        etInternalAiUrl.setText(internalAiUrl)
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
                    tvDiagInfo.text = "محلي مكتشف: $found"
                    if (!silent) notifyActionCompleted(true, "تم اكتشاف اللوحة على الشبكة المحلية", found)
                }
            } else if (!silent) {
                mainHandler.post {
                    notifyActionCompleted(true, "سيتم استخدام Firebase السحابي تلقائياً", "لم يُعثر على الكمبيوتر في نفس الشبكة")
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
        timeoutMs: Int = 6500
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
            put("chart_active", doc.optBoolean("chart_active", false))
            put("chart_tf", doc.optString("chart_tf", selectedChartTf))
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
                tvStatusBar.text = "افتح تبويب 'السجل والربط' وتأكد من رمز الربط"
            }
            return
        }

        pollTickCounter += 1
        val tick = pollTickCounter

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
                            errMsg = "بانتظار تشغيل سكربت smc_control_panel.py على الكمبيوتر"
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

            // 3) Directly poll Firestore items/answer so Web/Server Internal Gemini results appear instantly on Phone
            if (isFirestoreUrl(fbUrl) && connModeIdx != 1 && (tick % 2 == 0 || waitingForInternalGemini)) {
                try {
                    val room = code.lowercase(Locale.US)
                    val keyParam = URLEncoder.encode(fbSecret.ifBlank { DEFAULT_FB_API_KEY }, "UTF-8")
                    val ansUrl = "${firestoreBaseUrl()}/rooms/$room/items/answer?key=$keyParam"
                    val (asc, abody) = httpJson(ansUrl, "GET", timeoutMs = 5000)
                    if (asc == 200) {
                        val doc = fsDecodeDoc(abody)
                        val ansTs = doc.optLong("ts", 0L)
                        val ansName = doc.optString("name", "جيمناي الداخلي")
                        val ansText = doc.optString("text", "")
                        val isNewer = ansText.isNotBlank() && (ansTs > lastAnswerTs || (ansTs == 0L && ansText != answerText))
                        if (isNewer) {
                            lastAnswerTs = ansTs
                            val wasWaiting = waitingForInternalGemini
                            waitingForInternalGemini = false
                            mainHandler.post {
                                answerText = ansText
                                tvAnswerContent.text = ansText
                                if (ansName.isNotBlank()) tvAnswerLabel.text = ansName
                                if (wasWaiting) {
                                    progressBusy.visibility = View.GONE
                                    tabLayout.getTabAt(5)?.select()
                                    notifyActionCompleted(true, "تم استلام نتيجة تحليل جيمناي الداخلي", ansName)
                                }
                            }
                        }
                    }
                } catch (_: Throwable) {
                }
            }

            mainHandler.post {
                activeChannel = channel
                if (snap != null) {
                    applySnapshotToUi(snap, channel)
                } else {
                    tvChannelBadge.text = if (isFirestoreUrl(fbUrl)) "☁️ جاهز (جيمناي / Firebase)" else "🔴 غير متصل"
                    if (errMsg.isNotBlank() && !waitingForInternalGemini) tvStatusBar.text = errMsg
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
        tvMt5Status.setTextColor(Color.parseColor(if (mt5Ok) "#34D399" else "#FCA5A5"))

        val price = snap.optString("price", "")
        tvLivePrice.text = if (price.isNotBlank()) price else "—"

        val busy = snap.optBoolean("busy", false)
        val ai = snap.optBoolean("ai", false)
        val statusTxt = snap.optString("status", "جاهز")
        progressBusy.visibility = if (busy || ai) View.VISIBLE else View.GONE
        btnStop.isEnabled = ai || busy
        tvStatusBar.text = statusTxt

        // Detect completion of long async PC operations (connect / fetch / ai / fetch_ai)
        if (lastBusyState && !busy && pendingAsyncTask != null) {
            val doneTask = pendingAsyncTask
            pendingAsyncTask = null
            val ok = !statusTxt.startsWith("❌") && !statusTxt.startsWith("⚠")
            val label = when (doneTask) {
                "connect" -> if (mt5Ok) "تم الاتصال بمنصة MT5" else "فشل الاتصال بـ MT5"
                "fetch" -> "تم جلب البيانات الحية من MT5"
                "ai" -> "اكتمل تحليل الذكاء الاصطناعي"
                "fetch_ai" -> "اكتمل جلب البيانات والتحليل"
                else -> "تم إتمام العملية"
            }
            notifyActionCompleted(ok && (doneTask != "connect" || mt5Ok), label, statusTxt)
        }
        lastBusyState = busy

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
            val keys = mutableListOf("lists", "data", "file", "answer", "prompt")
            if (chartStreaming) {
                keys.add("chart")
            }
            keys.forEach { k ->
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
        pullContentAfter: String? = null,
        completionLabel: String? = null
    ) {
        val code = normCode(pairCode)
        if (code.length < 12) {
            if (!quiet) notifyActionCompleted(false, "رمز الربط غير مكتمل", "تحقق من تبويب السجل والربط")
            return
        }
        netExec.execute {
            try {
                val res = executeRemoteAction(code, action, params)
                val ok = res.optBoolean("ok", false)
                val err = res.optString("error", "")
                if (!ok) {
                    pendingAsyncTask = null
                    if (!quiet) {
                        notifyActionCompleted(false, "تعذر تنفيذ: ${completionLabel ?: action}", err.ifBlank { "تحقق من اتصال الكمبيوتر" })
                    }
                    return@execute
                }
                if (pullContentAfter != null) {
                    val waitMs = if (pullContentAfter == "chart") 950L else 650L
                    Thread.sleep(waitMs)
                    val pulled = pullContentBlocking(
                        pullContentAfter,
                        saveToDownloads = (pullContentAfter == "file" && action == "make_file")
                    )
                    if (completionLabel != null && pullContentAfter != "file") {
                        if (pulled || pullContentAfter != "chart") {
                            notifyActionCompleted(true, completionLabel)
                        }
                    }
                } else if (!quiet && completionLabel != null) {
                    notifyActionCompleted(true, completionLabel)
                }
            } catch (e: Throwable) {
                pendingAsyncTask = null
                if (!quiet) {
                    notifyActionCompleted(false, "خطأ في الاتصال", e.message ?: e.javaClass.simpleName)
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
                Thread.sleep(550)
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

    private fun pullContentAsync(key: String, saveToDownloads: Boolean, notifyLabel: String? = null) {
        netExec.execute {
            val ok = pullContentBlocking(key, saveToDownloads)
            if (notifyLabel != null) {
                notifyActionCompleted(ok, if (ok) notifyLabel else "تعذر سحب المحتوى ($key)")
            }
        }
    }

    private fun pullContentAndSaveFile() {
        netExec.execute {
            val ok = pullContentBlocking("file", saveToDownloads = true)
            if (!ok) {
                notifyActionCompleted(false, "لا يوجد ملف جاهز بعد", "اضغط 'إنشاء الملف فقط' أولاً")
            }
        }
    }

    private fun runFetchCreateAndDownloadWorkflow() {
        val code = normCode(pairCode)
        if (code.length < 12) {
            notifyActionCompleted(false, "رمز الربط غير مكتمل")
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
                    notifyActionCompleted(false, "فشل جلب البيانات الحية", r1.optString("error", ""))
                    return@execute
                }
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
                    notifyActionCompleted(false, "فشل إنشاء الملف", r2.optString("error", ""))
                    return@execute
                }
                mainHandler.post { tvStatusBar.text = "⬇️ 3/3 جاري استلام وحفظ الملف في الهاتف..." }
                Thread.sleep(800)
                val ok = pullContentBlocking("file", saveToDownloads = true)
                if (!ok) {
                    notifyActionCompleted(false, "تعذر استلام الملف النهائي")
                }
            } catch (e: Throwable) {
                notifyActionCompleted(false, "تعذر إتمام العملية المتكاملة", e.message ?: "")
            } finally {
                mainHandler.post { progressBusy.visibility = View.GONE }
            }
        }
    }

    private fun runInternalGeminiWorkflow(createFileFirst: Boolean) {
        val code = normCode(pairCode)
        if (code.length < 12) {
            notifyActionCompleted(false, "رمز الربط غير مكتمل")
            return
        }
        val selectedSym = spSymbol.selectedItem?.toString() ?: "XAUUSD"
        val currentPrompt = if (::etPrompt.isInitialized) etPrompt.text.toString() else promptText
        val params = collectParams()

        mainHandler.post {
            progressBusy.visibility = View.VISIBLE
            tvStatusBar.text = if (createFileFirst) {
                "✨ 1/3 جاري تجهيز البيانات وإنشاء الملف لمشاركته مع جيمناي الداخلي..."
            } else {
                "🤖 جاري إرسال الملف إلى جيمناي الداخلي للتحليل..."
            }
        }

        netExec.execute {
            try {
                if (createFileFirst) {
                    if (dataText.isBlank() && latestPulledDataText.isBlank()) {
                        mainHandler.post { tvStatusBar.text = "📥 1/3 جاري جلب البيانات الحية من MT5..." }
                        val rFetch = executeRemoteAction(code, "fetch", params)
                        if (rFetch.optBoolean("ok", false)) {
                            val deadline = System.currentTimeMillis() + 90000L
                            Thread.sleep(1500)
                            while (System.currentTimeMillis() < deadline) {
                                val s = lastSnap
                                if (s != null && !s.optBoolean("busy", false)) break
                                Thread.sleep(900)
                            }
                            pullContentBlocking("data", saveToDownloads = false)
                        }
                    }

                    mainHandler.post { tvStatusBar.text = "📄 2/3 جاري إنشاء ملف .txt على الكمبيوتر..." }
                    val rMake = executeRemoteAction(code, "make_file", params)
                    if (rMake.optBoolean("ok", false)) {
                        Thread.sleep(700)
                        pullContentBlocking("file", saveToDownloads = false)
                    }
                } else if (fileText.isBlank() && latestPulledFileText.isBlank()) {
                    pullContentBlocking("file", saveToDownloads = false)
                }

                val targetContent = latestPulledFileText
                    .ifBlank { fileText }
                    .ifBlank { latestPulledDataText }
                    .ifBlank { dataText }

                if (targetContent.isNotBlank() && internalAiUrl.isNotBlank()) {
                    mainHandler.post { tvStatusBar.text = "✨ 3/3 جاري مشاركة الملف مع جيمناي الداخلي..." }
                    try {
                        val payload = JSONObject().apply {
                            put("content", targetContent)
                            put("symbol", selectedSym)
                            put("prompt", currentPrompt)
                            put("roomId", code.lowercase(Locale.US))
                            put("pushToFirebase", true)
                        }.toString()
                        val (sc, body) = httpJson(internalAiUrl, "POST", payload, timeoutMs = 90000)
                        if (sc == 200 && body.trimStart().startsWith("{")) {
                            val res = JSONObject(body)
                            val ans = res.optString("answer", "")
                            if (res.optBoolean("ok", false) && ans.isNotBlank()) {
                                val lbl = "✨ تحليل جيمناي الداخلي (${res.optString("model", "gemini-4-hydrogen")})"
                                lastAnswerTs = System.currentTimeMillis() / 1000L
                                waitingForInternalGemini = false
                                mainHandler.post {
                                    progressBusy.visibility = View.GONE
                                    answerText = ans
                                    tvAnswerLabel.text = lbl
                                    tvAnswerContent.text = ans
                                    tabLayout.getTabAt(5)?.select()
                                    notifyActionCompleted(true, "تمت مشاركة الملف واكتمل التحليل في جيمناي الداخلي", selectedSym)
                                }
                                return@execute
                            }
                        }
                    } catch (_: Throwable) {
                        // Fall back seamlessly to Firebase/Local command relay below
                    }
                }

                // Fallback relay via Firebase/Local Bridge (fulfilled by Web Companion or PC)
                waitingForInternalGemini = true
                val actionName = if (createFileFirst) "make_file_internal_gemini" else "internal_gemini"
                val relayRes = executeRemoteAction(code, actionName, params)
                val relayOk = relayRes.optBoolean("ok", true)
                if (!relayOk) {
                    waitingForInternalGemini = false
                    mainHandler.post { progressBusy.visibility = View.GONE }
                    notifyActionCompleted(false, "تعذر تشغيل جيمناي الداخلي", relayRes.optString("error", ""))
                } else {
                    mainHandler.post {
                        tvStatusBar.text = "⏳ تم إرسال الملف لجيمناي الداخلي عبر Firebase — بانتظار النتيجة..."
                    }
                }
            } catch (e: Throwable) {
                waitingForInternalGemini = false
                mainHandler.post { progressBusy.visibility = View.GONE }
                notifyActionCompleted(false, "خطأ أثناء الاتصال بجيمناي الداخلي", e.message ?: "")
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

        if (key == "data") latestPulledDataText = text
        if (key == "file") latestPulledFileText = text
        if (key == "answer") {
            val tsVal = c.optLong("ts", 0L)
            if (tsVal > lastAnswerTs) lastAnswerTs = tsVal
        }

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
                        val msg = if (saved != null) "Downloads/SMC/$name" else name
                        notifyActionCompleted(true, "تم استلام وحفظ الملف بنجاح", msg)
                        tabLayout.getTabAt(4)?.select()
                    }
                }
                "answer" -> {
                    answerText = text
                    tvAnswerContent.text = text
                    if (name.isNotBlank() && name != "SMC_answer.txt") tvAnswerLabel.text = name
                    if (waitingForInternalGemini) {
                        waitingForInternalGemini = false
                        progressBusy.visibility = View.GONE
                        tabLayout.getTabAt(5)?.select()
                        notifyActionCompleted(true, "تم استلام نتيجة تحليل جيمناي الداخلي", name)
                    }
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
                "chart" -> {
                    applyChartJson(text)
                }
            }
        }
        return true
    }

    private fun applyChartJson(raw: String) {
        try {
            val js = JSONObject(raw)
            val sym = js.optString("symbol", "XAUUSD")
            val tf = js.optString("tf", selectedChartTf)
            val digits = js.optInt("digits", 2).coerceIn(0, 6)
            val bid = js.optDouble("bid", 0.0)
            val ask = js.optDouble("ask", bid)
            val updated = js.optString("updated", "")
            val arr = js.optJSONArray("candles") ?: return
            val list = ArrayList<CandleBar>(arr.length())
            for (i in 0 until arr.length()) {
                val row = arr.optJSONArray(i) ?: continue
                if (row.length() < 5) continue
                list.add(
                    CandleBar(
                        timeSec = row.optLong(0, 0L),
                        open = row.optDouble(1, 0.0),
                        high = row.optDouble(2, 0.0),
                        low = row.optDouble(3, 0.0),
                        close = row.optDouble(4, 0.0),
                        vol = row.optLong(5, 0L)
                    )
                )
            }
            if (list.isEmpty()) return
            chartSymbol = sym
            if (TF_NAMES.contains(tf)) selectedChartTf = tf
            chartDigits = digits
            chartBid = bid
            chartAsk = ask
            chartUpdatedAt = updated
            chartBars = list
            updateChartControlsUi()
            chartView.setChartData(sym, tf, digits, bid, ask, list)
            val fmt = "%.${digits}f"
            val last = list.last()
            tvChartHud.text = "$sym ($tf) | O:${String.format(Locale.US, fmt, last.open)} H:${String.format(Locale.US, fmt, last.high)} L:${String.format(Locale.US, fmt, last.low)} C:${String.format(Locale.US, fmt, last.close)} | Bid:${String.format(Locale.US, fmt, bid)} ($updated)"
        } catch (_: Throwable) {
        }
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
            notifyActionCompleted(false, "لا يوجد ملف لمشاركته", "استلم الملف أولاً")
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
            notifyActionCompleted(false, "لا يوجد نص للمشاركة")
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
            notifyActionCompleted(false, "لا يوجد محتوى لنسخه")
            return
        }
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText(label, text))
        notifyActionCompleted(true, "تم نسخ $label إلى الحافظة")
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private fun formatUnixTime(sec: Long, tf: String): String {
        val df = SimpleDateFormat(if (tf == "H4" || tf == "D1") "MM-dd HH:mm" else "HH:mm", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("GMT+03:00")
        }
        return df.format(Date(sec * 1000L))
    }

    // ==========================================================
    // Interactive Candlestick Canvas View (Pan + Pinch Zoom + Crosshair)
    // ==========================================================
    inner class CandleChartView(
        context: Context,
        private val onBarInspect: (CandleBar, Boolean) -> Unit
    ) : View(context) {

        private var bars: List<CandleBar> = emptyList()
        private var sym: String = "XAUUSD"
        private var tf: String = "M15"
        private var digits: Int = 2
        private var bid: Double = 0.0
        private var ask: Double = 0.0

        private var candleStepPx = dp(10).toFloat()
        private var viewOffset = 0
        private var dragStartX = 0f
        private var dragStartY = 0f
        private var dragStartOffset = 0
        private var isDragging = false
        private var crossX = -1f
        private var crossY = -1f
        private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop

        private val scaleDetector = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScale(detector: ScaleGestureDetector): Boolean {
                zoomBy(detector.scaleFactor)
                return true
            }
        })

        private val bgPaint = Paint().apply { color = Color.parseColor(COL_BG) }
        private val gridPaint = Paint().apply {
            color = Color.parseColor("#1E293B")
            strokeWidth = 1.5f
            pathEffect = DashPathEffect(floatArrayOf(6f, 6f), 0f)
        }
        private val axisPaint = Paint().apply {
            color = Color.parseColor("#334155")
            strokeWidth = 2f
        }
        private val axisTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#94A3B8")
            textSize = dp(10).toFloat()
            typeface = Typeface.MONOSPACE
        }
        private val emptyTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#64748B")
            textSize = dp(14).toFloat()
            textAlign = Paint.Align.CENTER
        }
        private val bullPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#10B981")
            strokeWidth = 2.5f
        }
        private val bearPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#EF4444")
            strokeWidth = 2.5f
        }
        private val bidLinePaint = Paint().apply {
            color = Color.parseColor("#38BDF8")
            strokeWidth = 2.5f
            pathEffect = DashPathEffect(floatArrayOf(10f, 6f), 0f)
        }
        private val bidTagPaint = Paint().apply {
            color = Color.parseColor("#0284C7")
        }
        private val bidTagTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = dp(10).toFloat()
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        }
        private val crossPaint = Paint().apply {
            color = Color.parseColor("#64748B")
            strokeWidth = 2f
            pathEffect = DashPathEffect(floatArrayOf(8f, 6f), 0f)
        }

        fun setChartData(s: String, t: String, d: Int, b: Double, a: Double, list: List<CandleBar>) {
            sym = s
            tf = t
            digits = d
            bid = b
            ask = a
            bars = list
            viewOffset = viewOffset.coerceIn(0, max(0, bars.size - 8))
            invalidate()
        }

        fun zoomBy(factor: Float) {
            candleStepPx = (candleStepPx * factor).coerceIn(dp(4).toFloat(), dp(36).toFloat())
            invalidate()
        }

        fun resetView() {
            viewOffset = 0
            candleStepPx = dp(10).toFloat()
            crossX = -1f
            crossY = -1f
            invalidate()
        }

        override fun onTouchEvent(event: MotionEvent): Boolean {
            scaleDetector.onTouchEvent(event)
            if (scaleDetector.isInProgress) {
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    parent?.requestDisallowInterceptTouchEvent(true)
                    dragStartX = event.x
                    dragStartY = event.y
                    dragStartOffset = viewOffset
                    isDragging = false
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.x - dragStartX
                    val dy = event.y - dragStartY
                    if (!isDragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) {
                        isDragging = true
                    }
                    if (isDragging && bars.isNotEmpty()) {
                        val shift = (dx / max(4f, candleStepPx)).roundToInt()
                        val maxOff = max(0, bars.size - 8)
                        viewOffset = (dragStartOffset + shift).coerceIn(0, maxOff)
                        invalidate()
                    }
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    if (!isDragging) {
                        if (crossX >= 0f && abs(event.x - crossX) < dp(18) && abs(event.y - crossY) < dp(18)) {
                            crossX = -1f
                            crossY = -1f
                            if (bars.isNotEmpty()) onBarInspect(bars.last(), false)
                        } else {
                            crossX = event.x
                            crossY = event.y
                            inspectAt(crossX)
                        }
                        invalidate()
                    }
                    return true
                }
            }
            return super.onTouchEvent(event)
        }

        private fun inspectAt(xPos: Float) {
            if (bars.isEmpty() || width <= 0) return
            val padL = dp(10).toFloat()
            val padR = dp(68).toFloat()
            val plotW = max(40f, width - padL - padR)
            val step = max(4f, candleStepPx)
            val visibleCount = max(8, (plotW / step).toInt())
            val endIdx = max(1, bars.size - viewOffset)
            val startIdx = max(0, endIdx - visibleCount)
            val vis = bars.subList(startIdx, endIdx)
            if (vis.isEmpty()) return
            val idx = ((xPos - padL) / step).toInt().coerceIn(0, vis.size - 1)
            onBarInspect(vis[idx], true)
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val w = width.toFloat()
            val h = height.toFloat()
            canvas.drawRect(0f, 0f, w, h, bgPaint)

            if (bars.isEmpty()) {
                canvas.drawText("اضغط 'عرض الرسم البياني' لنقل الشموع الحية", w / 2f, h / 2f, emptyTextPaint)
                return
            }

            val padL = dp(10).toFloat()
            val padT = dp(16).toFloat()
            val padR = dp(68).toFloat()
            val padB = dp(26).toFloat()
            val plotW = max(40f, w - padL - padR)
            val plotH = max(40f, h - padT - padB)

            val step = max(4f, candleStepPx)
            val visibleCount = max(8, (plotW / step).toInt())
            val endIdx = max(1, bars.size - viewOffset)
            val startIdx = max(0, endIdx - visibleCount)
            val vis = bars.subList(startIdx, endIdx)
            if (vis.isEmpty()) return

            var hi = vis.maxOf { it.high }
            var lo = vis.minOf { it.low }
            if (bid > 0 && viewOffset == 0) {
                hi = max(hi, bid)
                lo = min(lo, bid)
            }
            var rng = hi - lo
            if (rng <= 0.0) rng = max(abs(hi) * 0.001, 0.01)
            val pMax = hi + rng * 0.08
            val pMin = lo - rng * 0.08
            val pRng = max(1e-9, pMax - pMin)

            fun yOf(p: Double): Float = (padT + ((pMax - p) / pRng) * plotH).toFloat()

            val fmt = "%.${digits.coerceIn(0, 6)}f"
            for (i in 0..5) {
                val frac = i / 5.0
                val yy = (padT + frac * plotH).toFloat()
                val pv = pMax - frac * pRng
                canvas.drawLine(padL, yy, w - padR, yy, gridPaint)
                canvas.drawText(String.format(Locale.US, fmt, pv), w - padR + dp(5), yy + dp(3), axisTextPaint)
            }

            canvas.drawLine(w - padR, padT, w - padR, h - padB, axisPaint)
            canvas.drawLine(padL, h - padB, w - padR, h - padB, axisPaint)

            val bodyHalf = max(1.5f, step * 0.33f)
            val labelEvery = max(1, vis.size / 5)
            for (i in vis.indices) {
                val cx = padL + (i + 0.5f) * step
                if (cx > w - padR - 2f) break
                val bar = vis[i]
                val paint = if (bar.close >= bar.open) bullPaint else bearPaint
                val yHi = yOf(bar.high)
                val yLo = yOf(bar.low)
                val yOp = yOf(bar.open)
                val yCl = yOf(bar.close)
                canvas.drawLine(cx, yHi, cx, yLo, paint)
                val topY = min(yOp, yCl)
                val botY = max(max(yOp, yCl), topY + 2f)
                canvas.drawRect(cx - bodyHalf, topY, cx + bodyHalf, botY, paint)

                if (i % labelEvery == 0) {
                    val lbl = formatUnixTime(bar.timeSec, tf)
                    canvas.drawText(lbl, cx - dp(14), h - dp(8), axisTextPaint)
                }
            }

            if (bid > 0 && bid in pMin..pMax) {
                val yb = yOf(bid)
                canvas.drawLine(padL, yb, w - padR, yb, bidLinePaint)
                canvas.drawRect(w - padR + 2f, yb - dp(9), w - 2f, yb + dp(9), bidTagPaint)
                canvas.drawText(String.format(Locale.US, fmt, bid), w - padR + dp(5), yb + dp(3), bidTagTextPaint)
            }

            if (crossX in padL..(w - padR) && crossY in padT..(h - padB)) {
                val idx = ((crossX - padL) / step).toInt().coerceIn(0, vis.size - 1)
                val sx = padL + (idx + 0.5f) * step
                canvas.drawLine(sx, padT, sx, h - padB, crossPaint)
                canvas.drawLine(padL, crossY, w - padR, crossY, crossPaint)
            }
        }
    }
}
