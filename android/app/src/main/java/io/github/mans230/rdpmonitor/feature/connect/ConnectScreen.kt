package io.github.mans230.rdpmonitor.feature.connect

import android.content.ClipboardManager
import android.content.ClipData
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.core.security.PrivateOrigin
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.coroutines.delay

internal fun serverFormError(name: String, address: String): String? = when {
    name.isBlank() -> "Enter a server name."
    name.trim().length > 60 -> "Use 60 characters or fewer for the name."
    runCatching { PrivateOrigin.parse(address) }.isFailure -> "Use your server's private HTTPS .ts.net address."
    else -> null
}

@Composable fun ConnectScreen(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit, modifier: Modifier = Modifier,
                              connect: (String, String) -> Unit = { name, address -> model.connect(name, address) }) {
    var name by rememberSaveable(state.selected?.id) { mutableStateOf(state.selected?.name.orEmpty()) }
    var address by rememberSaveable(state.selected?.id) { mutableStateOf(state.selected?.origin.orEmpty()) }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    val clipboard = LocalContext.current.getSystemService(ClipboardManager::class.java)
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val approvalView = remember { BringIntoViewRequester() }
    val available = !state.busy && !state.actionBusy
    val labelSize = if (LocalConfiguration.current.screenWidthDp < 640) 16.sp else 14.sp
    val back = LocalOnboardingBack.current
    val servers = LocalServerWorkspace.current
    LaunchedEffect(state.pairingUrl, state.pairingExpiresAt) {
        if (state.pairingUrl != null) { delay((state.pairingExpiresAt - System.currentTimeMillis()).coerceAtLeast(0)); model.expirePairing() }
    }
    LaunchedEffect(state.pairingUrl) {
        if (state.pairingUrl != null) { withFrameNanos { }; approvalView.bringIntoView() }
    }
    Box(modifier) {
        OnboardingScaffold(onBack = { if (available) { if (state.snapshot != null) model.closeConnections() else back() } }, actions = {
            if (state.profiles.isNotEmpty() && servers != null) MotionIconButton(onClick = servers, enabled = available, modifier = Modifier.size(44.dp)) { Icon(Icons.Outlined.Dns, "Saved servers", Modifier.size(18.dp)) }
        }, footer = {
            if (state.pairingUrl != null) OnboardingPrimary("Continue in browser", { openBrowser(state.pairingUrl) }, available)
            else OnboardingPrimary("Connect server", {
                error = serverFormError(name, address)
                if (error == null) { focus.clearFocus(); keyboard?.hide(); connect(name.trim(), address.trim()) }
            }, available)
        }) {
            OnboardingBody {
                Spacer(Modifier.height(31.dp))
                OnboardingMark(small = true); Spacer(Modifier.height(22.dp))
                OnboardingHeadline("Add your server.", server = true); Spacer(Modifier.height(32.dp))
                BoxWithConstraints {
                val panelInset = if (maxWidth < 310.dp) 17.dp else 20.dp
                Surface(color = androidx.compose.ui.graphics.lerp(Ground, Tray, .72f), shape = RoundedCornerShape(16.dp)) {
                    Column(Modifier.padding(4.dp)) {
                        CossPanel(inset = panelInset) {
                            Column(verticalArrangement = Arrangement.spacedBy(25.dp)) {
                                CossField("Server name", name, { name = it; error = null; model.clearMessage() }, placeholder = "Work server", labelStyle = MaterialTheme.typography.labelLarge.copy(fontSize = labelSize), enabled = available && state.pairingUrl == null)
                                CossField("Server address", address, { address = it; error = null; model.clearMessage() }, placeholder = "https://server.tailnet.ts.net", labelStyle = MaterialTheme.typography.labelLarge.copy(fontSize = labelSize),
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), enabled = available && state.pairingUrl == null)
                            }
                        }
                    }
                }
                }
                (error ?: state.message)?.let { Spacer(Modifier.height(18.dp)); Text(it, style = MaterialTheme.typography.bodyMedium) }
                if (state.actionBusy) { Spacer(Modifier.height(12.dp)); Text("Finish the current server operation first.", color = Muted) }
                state.pairingUrl?.let {
                    Spacer(Modifier.height(18.dp))
                    CossFrame("Approve connection", scopeTitle(state.requestedScope)) { CossPanel {
                        Text(state.pairingCode.orEmpty(), Modifier.bringIntoViewRequester(approvalView), style = ReadingStyle.copy(fontSize = 20.sp))
                        Text("Match this code in the browser, then approve.", color = Muted)
                        CossTextButton(onClick = { clipboard.setPrimaryClip(ClipData.newPlainText("Pairing code", state.pairingCode.orEmpty())) }) { Text("Copy code") }
                        CossTextButton(onClick = model::cancelPairing) { Text("Cancel pairing") }
                    } }
                }
                if (state.message != null && state.selected != null && state.pairingUrl == null) CossTextButton(onClick = { openBrowser(state.selected.origin + "/") }) { Text("Open web panel") }
                Spacer(Modifier.height(16.dp))
            }
        }
    }
}
