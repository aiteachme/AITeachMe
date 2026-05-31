package com.aiteachme.android.core.session

import android.content.Context
import java.util.UUID

class SessionStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getDeviceKey(): String {
        val existing = prefs.getString(KEY_DEVICE_KEY, null)
        if (existing != null && DEVICE_KEY_RE.matches(existing)) {
            return existing
        }
        val generated = "dk_${UUID.randomUUID()}"
        prefs.edit().putString(KEY_DEVICE_KEY, generated).apply()
        return generated
    }

    fun getAccessToken(): String? {
        return prefs.getString(KEY_ACCESS_TOKEN, null)?.takeIf { it.isNotBlank() }
    }

    fun saveAccessToken(token: String?) {
        if (token.isNullOrBlank()) {
            clearAccessToken()
            return
        }
        prefs.edit().putString(KEY_ACCESS_TOKEN, token).apply()
    }

    fun clearAccessToken() {
        prefs.edit().remove(KEY_ACCESS_TOKEN).apply()
    }

    private companion object {
        const val PREFS_NAME = "aiteachme_session"
        const val KEY_DEVICE_KEY = "device_key"
        const val KEY_ACCESS_TOKEN = "access_token"
        val DEVICE_KEY_RE = Regex("^[A-Za-z0-9._:-]{8,128}$")
    }
}
