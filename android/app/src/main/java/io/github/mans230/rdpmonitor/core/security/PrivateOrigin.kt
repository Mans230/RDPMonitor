package io.github.mans230.rdpmonitor.core.security

import java.net.URI
import java.util.Locale

object PrivateOrigin {
    fun parse(input: String): String {
        val uri = URI(input.trim())
        val host = uri.host?.lowercase(Locale.ROOT) ?: error("Enter a complete private HTTPS address.")
        require(uri.scheme == "https" && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) {
            "Use the HTTPS Tailscale address without passwords, tokens or query parameters."
        }
        require(uri.port == -1 || uri.port == 443) { "Use the standard HTTPS Tailscale Serve address." }
        require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") { "Enter the server address without a page path." }
        require(host.endsWith(".ts.net") && host.length <= 253 && host.split('.').all {
            it.matches(Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"))
        }) { "Use the server's private .ts.net hostname; public IP access is not supported." }
        return "https://$host"
    }

    fun sameServerUrl(origin: String, input: String): String {
        val uri = URI(input)
        val actual = parse("${uri.scheme}://${uri.rawAuthority}")
        require(actual == parse(origin) && uri.rawUserInfo == null && uri.rawFragment == null) {
            "The sign-in address does not belong to this server."
        }
        return uri.toASCIIString()
    }
}
