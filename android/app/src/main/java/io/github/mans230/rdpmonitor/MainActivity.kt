package io.github.mans230.rdpmonitor

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.browser.customtabs.CustomTabsIntent
import androidx.core.net.toUri
import io.github.mans230.rdpmonitor.ui.RdpApp
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme

class MainActivity: ComponentActivity() {
    private val model: RdpViewModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); enableEdgeToEdge()
        setContent { RdpTheme { RdpApp(model, ::openBrowser) } }
        if (savedInstanceState == null || model.hasPendingPairing()) intent?.dataString?.let(model::callback)
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); intent.dataString?.let(model::callback) }
    override fun onStart() { super.onStart(); model.foreground(true) }
    override fun onStop() { model.foreground(false); super.onStop() }
    private fun openBrowser(url: String) {
        try { CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(this, url.toUri()) }
        catch (_: android.content.ActivityNotFoundException) {
            android.widget.Toast.makeText(this, "Install a browser to use secure Passkey sign-in.", android.widget.Toast.LENGTH_LONG).show()
        }
    }
}
