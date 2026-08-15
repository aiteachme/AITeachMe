package com.aiteachme.android.core.network

import com.aiteachme.android.core.session.SessionStore
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Persist HttpOnly authentication cookies without exposing them to UI code. */
class PersistentCookieJar(
    private val sessionStore: SessionStore,
) : CookieJar {
    @Synchronized
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val now = System.currentTimeMillis()
        val stored = readCookies(sessionStore.getCookieRecords(), now).toMutableList()
        cookies.forEach { incoming ->
            stored.removeAll { (_, cookie) -> cookie.sameIdentityAs(incoming) }
            if (incoming.expiresAt > now) {
                stored += url to incoming
            }
        }
        persist(stored)
    }

    @Synchronized
    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        val records = sessionStore.getCookieRecords()
        val stored = readCookies(records, now)
        val normalized = encode(stored)
        if (normalized != records) {
            sessionStore.saveCookieRecords(normalized)
        }
        return stored.map { it.second }.filter { it.matches(url) }
    }

    private fun readCookies(records: Set<String>, now: Long): List<Pair<HttpUrl, Cookie>> {
        return records.mapNotNull { record ->
            val separator = record.indexOf(RECORD_SEPARATOR)
            if (separator <= 0 || separator >= record.lastIndex) {
                return@mapNotNull null
            }
            val origin = record.substring(0, separator).toHttpUrlOrNull()
                ?: return@mapNotNull null
            val cookie = Cookie.parse(origin, record.substring(separator + 1))
                ?: return@mapNotNull null
            (origin to cookie).takeIf { cookie.expiresAt > now }
        }
    }

    private fun persist(cookies: List<Pair<HttpUrl, Cookie>>) {
        sessionStore.saveCookieRecords(encode(cookies))
    }

    private fun encode(cookies: List<Pair<HttpUrl, Cookie>>): Set<String> {
        return cookies.mapTo(linkedSetOf()) { (origin, cookie) ->
            "${origin}$RECORD_SEPARATOR${cookie}"
        }
    }

    private fun Cookie.sameIdentityAs(other: Cookie): Boolean {
        return name == other.name && domain == other.domain && path == other.path
    }

    private companion object {
        const val RECORD_SEPARATOR = '\u001F'
    }
}
