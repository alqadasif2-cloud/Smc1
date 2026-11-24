import JSZip from 'jszip';

import pythonPanelRaw from '../../pc-script/smc_control_panel.py?raw';
import androidSettingsRaw from '../../android-app/settings.gradle.kts?raw';
import androidRootBuildRaw from '../../android-app/build.gradle.kts?raw';
import androidGradlePropsRaw from '../../android-app/gradle.properties?raw';
import androidAppBuildRaw from '../../android-app/app/build.gradle.kts?raw';
import androidManifestRaw from '../../android-app/app/src/main/AndroidManifest.xml?raw';
import androidIconRaw from '../../android-app/app/src/main/res/drawable/ic_smc_launcher.xml?raw';
import androidThemesRaw from '../../android-app/app/src/main/res/values/themes.xml?raw';
import androidMainActivityRaw from '../../android-app/app/src/main/java/com/smc/phone/MainActivity.kt?raw';

const STANDALONE_WORKFLOW_YML = `name: Build SMC Phone APK

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]
  workflow_dispatch:

jobs:
  build-apk:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Set up Gradle
        uses: gradle/actions/setup-gradle@v4
        with:
          gradle-version: '8.7'

      - name: Accept Android SDK licenses
        run: |
          if [ -n "$ANDROID_HOME" ] && [ -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
            yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null 2>&1 || true
          fi

      - name: Build Debug APK
        run: gradle assembleDebug --no-daemon --stacktrace

      - name: Upload APK Artifact
        uses: actions/upload-artifact@v4
        with:
          name: SMC-Phone-debug-apk
          path: app/build/outputs/apk/debug/*.apk
          if-no-files-found: error
`;

const STANDALONE_README = `# SMC Phone — تطبيق الأندرويد للتحكم عن بُعد بلوحة SMC

## المميزات
- جميع أزرار التحكم الموجودة في اللوحة الأم (MT5، جلب البيانات الحية، إنشاء الملف، إرسال لـ Gemini / Claude، Telegram، الإيقاف، تعديل الأوامر).
- تبديل تلقائي بين الاتصال المحلي (Wi-Fi عبر UDP + HTTP) و Firebase Firestore (مربوط ومفعّل افتراضياً).
- حفظ الملفات المستلمة (.txt) مباشرة في مجلد \`Downloads/SMC\` على الهاتف مع إمكانية المشاركة الفورية.

## تحويل المشروع إلى APK عبر GitHub Actions (بدون أخطاء)
1. ارفع محتويات هذا المجلد إلى مستودع GitHub جديد (تأكد من وجود مجلد \`.github/workflows/build-apk.yml\`).
2. افتح تبويب **Actions** في GitHub.
3. سيبدأ بناء ملف APK تلقائياً؛ عند الانتهاء اضغط على **SMC-Phone-debug-apk** لتحميل ملف \`app-debug.apk\`.
`;

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadTextAsset(content: string, fileName: string): void {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  triggerBlobDownload(blob, fileName);
}

export function downloadPythonScript(): void {
  downloadTextAsset(pythonPanelRaw, 'smc_control_panel.py');
}

export function downloadMainActivityKt(): void {
  downloadTextAsset(androidMainActivityRaw, 'MainActivity.kt');
}

export async function downloadAndroidGitHubZip(): Promise<void> {
  const zip = new JSZip();
  zip.file('.github/workflows/build-apk.yml', STANDALONE_WORKFLOW_YML);
  zip.file('README.md', STANDALONE_README);
  zip.file('settings.gradle.kts', androidSettingsRaw);
  zip.file('build.gradle.kts', androidRootBuildRaw);
  zip.file('gradle.properties', androidGradlePropsRaw);
  zip.file('app/build.gradle.kts', androidAppBuildRaw);
  zip.file('app/src/main/AndroidManifest.xml', androidManifestRaw);
  zip.file('app/src/main/res/drawable/ic_smc_launcher.xml', androidIconRaw);
  zip.file('app/src/main/res/values/themes.xml', androidThemesRaw);
  zip.file('app/src/main/java/com/smc/phone/MainActivity.kt', androidMainActivityRaw);

  const blob = await zip.generateAsync({ type: 'blob' });
  triggerBlobDownload(blob, 'SMC-Phone-GitHub-APK.zip');
}

export const EXPORT_PREVIEWS = {
  pythonLines: pythonPanelRaw.split('\n').length,
  kotlinLines: androidMainActivityRaw.split('\n').length,
  workflowYml: STANDALONE_WORKFLOW_YML,
  pythonRaw: pythonPanelRaw,
  kotlinRaw: androidMainActivityRaw,
};
