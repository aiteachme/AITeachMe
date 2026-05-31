plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

fun configValue(propertyName: String, envName: String): String? =
    providers.gradleProperty(propertyName)
        .orElse(providers.environmentVariable(envName))
        .orNull
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

fun buildConfigString(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

val publicBackendApiUrl = "https://umlxyfrxsjyp.sealosbja.site"
val configuredAndroidApiUrl = configValue("aiteachmeAndroidApiUrl", "AITEACHME_ANDROID_API_URL")
val debugDefaultApiUrl = (configuredAndroidApiUrl ?: "http://10.0.2.2:9020").trimEnd('/')
val releaseDefaultApiUrl = (configuredAndroidApiUrl ?: publicBackendApiUrl).trimEnd('/')
val releaseKeystoreFile = configValue("aiteachmeAndroidKeystoreFile", "AITEACHME_ANDROID_KEYSTORE_FILE")
val releaseKeystorePassword = configValue("aiteachmeAndroidKeystorePassword", "AITEACHME_ANDROID_KEYSTORE_PASSWORD")
val releaseKeyAlias = configValue("aiteachmeAndroidKeyAlias", "AITEACHME_ANDROID_KEY_ALIAS")
val releaseKeyPassword = configValue("aiteachmeAndroidKeyPassword", "AITEACHME_ANDROID_KEY_PASSWORD")
val releaseSigningConfigured = listOf(
    releaseKeystoreFile,
    releaseKeystorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { it != null }
val releaseSigningPartiallyConfigured = listOf(
    releaseKeystoreFile,
    releaseKeystorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).any { it != null } && !releaseSigningConfigured

check(!releaseSigningPartiallyConfigured) {
    "Android release signing is partially configured. Set all AITEACHME_ANDROID_KEYSTORE_FILE, AITEACHME_ANDROID_KEYSTORE_PASSWORD, AITEACHME_ANDROID_KEY_ALIAS, and AITEACHME_ANDROID_KEY_PASSWORD, or leave all unset for an unsigned release."
}

android {
    namespace = "com.aiteachme.android"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.aiteachme.android"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        val dailyWallpaperUrlTemplate = configValue(
            "aiteachmeAndroidWallpaperUrlTemplate",
            "AITEACHME_ANDROID_WALLPAPER_URL_TEMPLATE",
        ) ?: "https://picsum.photos/seed/aiteachme-{seed}/1080/2408.jpg"

        buildConfigField("String", "DEFAULT_API_BASE_URL", buildConfigString(debugDefaultApiUrl))
        buildConfigField(
            "String",
            "WALLPAPER_URL_TEMPLATE",
            buildConfigString(dailyWallpaperUrlTemplate),
        )
    }

    signingConfigs {
        if (releaseSigningConfigured) {
            create("release") {
                storeFile = rootProject.file(requireNotNull(releaseKeystoreFile))
                storePassword = requireNotNull(releaseKeystorePassword)
                keyAlias = requireNotNull(releaseKeyAlias)
                keyPassword = requireNotNull(releaseKeyPassword)
            }
        }
    }

    buildTypes {
        debug {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = false
            manifestPlaceholders["usesCleartextTraffic"] = "false"
            buildConfigField("String", "DEFAULT_API_BASE_URL", buildConfigString(releaseDefaultApiUrl))
            if (releaseSigningConfigured) {
                signingConfig = signingConfigs.getByName("release")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material.icons.extended)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.okhttp.logging)
    implementation(libs.retrofit.core)
    implementation(libs.retrofit.gson)
    implementation(libs.markwon.core)
    implementation(libs.markwon.ext.tables)
    implementation(libs.markwon.ext.latex)
    implementation(libs.markwon.html)
    implementation(libs.markwon.inline.parser)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
