package io.github.mans230.rdpmonitor.feature.connect

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.platform.LocalContext
import android.content.ClipboardManager
import android.content.ClipData
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun ConnectScreen(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit, modifier: Modifier = Modifier) {
    var name by rememberSaveable(state.selected?.id) { mutableStateOf(state.selected?.name.orEmpty()) }
    var address by rememberSaveable(state.selected?.id) { mutableStateOf(state.selected?.origin.orEmpty()) }
    val scroll = rememberScrollState()
    val coroutine = rememberCoroutineScope()
    val clipboard = LocalContext.current.getSystemService(ClipboardManager::class.java)
    val available = !state.busy && !state.actionBusy
    LaunchedEffect(state.pairingUrl, state.pairingExpiresAt) {
        if (state.pairingUrl != null) { delay((state.pairingExpiresAt - System.currentTimeMillis()).coerceAtLeast(0)); model.expirePairing() }
    }
    Column(modifier.fillMaxSize().verticalScroll(scroll).padding(20.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { PulseMark(); Text("RDPMonitor", style = MaterialTheme.typography.titleLarge) }
        if (state.snapshot != null && state.connectionScreen) {
            TextButton(onClick = model::closeConnections) { Text("Back to ${if (state.demo) "demo" else state.selected?.name ?: "monitor"}") }
            Notice(if (state.demo) "Choose a server below, or return to the demo." else if (state.connected) "Your current server session is kept. Opening this screen does not sign you out." else "The previous readings are stale. Sign in again to resume monitoring.")
        }
        PageTitle("Your RDP connectors", "Add a server's private HTTPS address. Each connector keeps its own authorization.")
        if (state.actionBusy) Notice("A server operation is still running. Return to the monitor to see progress before changing servers.")
        Notice("Connect Tailscale on this device. Sign-in uses your saved passkey; new keys require your approval in Telegram.")
        Section("Private connection") {
            Text("Access requested", style = MaterialTheme.typography.titleMedium)
            listOf("monitoring:read", "administration").forEach { scope ->
                Row(Modifier.fillMaxWidth().clickable(enabled = available) { model.chooseScope(scope) }.heightIn(min = 48.dp)) {
                    RadioButton(selected = state.requestedScope == scope, onClick = { model.chooseScope(scope) }, enabled = available)
                    Column(Modifier.weight(1f).padding(top = 10.dp)) {
                        Text(scopeTitle(scope))
                        Text(if (scope == "administration") "Manage server settings and operations after confirmation" else "Read monitoring data without management permissions", color = Muted, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Server name") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), enabled = available && state.pairingUrl == null)
            OutlinedTextField(value = address, onValueChange = { address = it }, label = { Text("Private HTTPS address") },
                placeholder = { Text("https://server.tailnet.ts.net") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth(), enabled = available && state.pairingUrl == null)
            state.message?.let { Notice(it) }
            MotionButton(onClick = { model.connect(name, address) }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                enabled = available && state.pairingUrl == null, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.onSurface, contentColor = Ground)) {
                if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Ground)
                else Text("Check private connection")
            }
            state.pairingUrl?.let { url ->
                Text("Ready to approve ${scopeTitle(state.requestedScope).lowercase()} access", style = MaterialTheme.typography.titleMedium)
                Text(state.pairingCode.orEmpty(), style = ReadingStyle)
                Text("Read or copy this code first. In the browser, sign in with your existing Passkey, compare the code, then approve. Return here automatically after approval.", color = Muted)
                TextButton(onClick = { clipboard.setPrimaryClip(ClipData.newPlainText("Pairing code", state.pairingCode.orEmpty())) }) { Text("Copy pairing code") }
                Button(onClick = { openBrowser(url) }, modifier = Modifier.fillMaxWidth()) { Text("Continue in browser") }
                Text("Waiting for approval · request expires after 10 minutes", color = Muted)
                OutlinedButton(onClick = model::cancelPairing) { Text("Cancel pairing") }
            }
            state.selected?.let { profile ->
                TextButton(onClick = { openBrowser(profile.origin + "/") }, modifier = Modifier.fillMaxWidth()) { Text("Open secure web panel") }
            }
        }
        if (state.profiles.isNotEmpty()) {
            Section("Saved servers", "Addresses are stored on this device. No bot token is needed.") {
                state.profiles.forEach { profile ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Column(Modifier.weight(1f).clickable(enabled = available) { model.cancelPairing(); name = profile.name; address = profile.origin; coroutine.launch { scroll.animateScrollTo(0) } }.padding(vertical = 8.dp)) {
                            Text(profile.name, style = MaterialTheme.typography.bodyLarge)
                            Text(profile.origin.removePrefix("https://"), color = Muted, style = MaterialTheme.typography.bodyMedium)
                            Text(if (address == profile.origin) "Selected above" else "Tap to select this server", color = Signal, style = MaterialTheme.typography.bodySmall)
                        }
                        IconButton(onClick = { model.remove(profile) }, enabled = available) { Icon(Icons.Outlined.Close, "Remove saved server ${profile.name}") }
                    }
                }
            }
        }
        OutlinedButton(onClick = model::preview, enabled = available, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Explore offline demo") }
        Text("The demo uses labelled sample data and cannot change a server.", color = Muted, style = MaterialTheme.typography.bodyMedium)
    }
}
