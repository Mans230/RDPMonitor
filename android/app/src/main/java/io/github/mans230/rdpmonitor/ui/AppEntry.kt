package io.github.mans230.rdpmonitor.ui

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.NoCredentialException
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.core.security.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable fun AppEntry(model: RdpViewModel, openBrowser: (String) -> Unit,
    signIn: suspend (Context, String) -> GoogleProfile = GoogleIdentity::signIn) {
    val context = LocalContext.current
    val preferences = remember { context.getSharedPreferences("app_identity", Context.MODE_PRIVATE) }
    var profile by remember { mutableStateOf(preferences.getString("subject", null)?.let { GoogleProfile(it, preferences.getString("email", "").orEmpty(), preferences.getString("name", "").orEmpty()) }) }
    val state by model.state.collectAsStateWithLifecycle()
    var inside by rememberSaveable { mutableStateOf(profile != null || model.hasPendingPairing()) }
    var signingIn by remember { mutableStateOf(false) }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var account by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(state.snapshot, state.pairingUrl, state.busy) {
        if (state.snapshot != null || state.pairingUrl != null || state.busy) inside = true
    }
    BackHandler(enabled = inside && state.snapshot == null && !state.busy && !signingIn) { inside = false }
    fun privateWorkspace() {
        if (preferences.getString("connector_owner", "private") != "private") {
            if (!model.signOutApp()) return
            preferences.edit().putString("connector_owner", "private").remove("subject").remove("email").remove("name").commit()
            profile = null; model.appIdentityChanged()
        }
        inside = true; message = null
    }
    Box(Modifier.fillMaxSize()) {
        if (!inside) Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(28.dp).then(pageMotion("welcome")), verticalArrangement = Arrangement.spacedBy(28.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { PulseMark(); Text("RDPMonitor", style = MaterialTheme.typography.titleMedium) }
            Spacer(Modifier.height(24.dp))
            PageTitle("Your servers. One place.", "Sign in, add your private RDP connectors, and keep an eye on what matters.")
            Section("Welcome") {
                Text("Use your Google account for your app workspace. Your servers still require Tailscale and Passkey approval.")
                MotionButton(onClick = {
                    signingIn = true; message = null
                    scope.launch {
                        try {
                            val identity = signIn(context, BuildConfig.GOOGLE_WEB_CLIENT_ID)
                            if (!model.signOutApp()) { message = "Finish the running server operation before switching accounts."; return@launch }
                            preferences.edit().putString("connector_owner", identity.subject).putString("subject", identity.subject).putString("email", identity.email).putString("name", identity.name).commit()
                            profile = identity; model.appIdentityChanged(); inside = true
                        } catch (_: GetCredentialCancellationException) { message = "Sign-in cancelled. You can try again." }
                        catch (_: NoCredentialException) { message = "No Google account is available. Add an account in Android settings, then try again." }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { message = "Google sign-in could not finish. Check the connection and the app's OAuth configuration, then try again." }
                        finally { signingIn = false }
                    }
                }, enabled = !signingIn && BuildConfig.GOOGLE_WEB_CLIENT_ID.isNotBlank(), modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Continue with Google") }
                if (BuildConfig.GOOGLE_WEB_CLIENT_ID.isBlank()) Text("Google sign-in is not configured in this build.", color = Muted)
                profile?.let { identity -> CossOutlinedButton(onClick = { inside = true }, modifier = Modifier.fillMaxWidth()) { Text("Continue as ${identity.name}") } }
                message?.let { Notice(it, true) }
            }
            CossTextButton(onClick = ::privateWorkspace, enabled = !signingIn) { Text("Use a private workspace without Google") }
            CossOutlinedButton(onClick = { privateWorkspace(); model.preview() }, enabled = !signingIn, modifier = Modifier.fillMaxWidth()) { Text("Explore offline demo") }
            Text("Connectors are saved on this device. Google sign-in does not sync server addresses, passwords or Passkeys.", color = Muted, style = MaterialTheme.typography.bodySmall)
        } else Column(Modifier.fillMaxSize()) {
            if (state.snapshot == null || state.connectionScreen) Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 20.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                CossTextButton(onClick = { account = true }, modifier = Modifier.weight(1f), enabled = !state.busy && !state.actionBusy) { Text(profile?.name ?: "Private workspace", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                CossTextButton(onClick = { if (!state.busy && !state.actionBusy) inside = false }, enabled = !state.busy && !state.actionBusy) { Text("Account") }
            }
            Box(Modifier.weight(1f).then(pageMotion(if (state.snapshot == null || state.connectionScreen) "connectors" else "monitor"))) { RdpApp(model, openBrowser) }
        }
        if (signingIn) LoadingPage("Signing in with Google", "Choose your account, then wait for verification.")
        else if (inside && state.busy && state.snapshot == null) LoadingPage("Connecting securely", state.selected?.name ?: "Checking your private connection…")
        if (account) CossDialog(onDismissRequest = { account = false }, title = { Text(profile?.name ?: "Private workspace") }, text = { Text(profile?.email ?: "Your connectors and authorization stay on this device.") }, confirmButton = {
            CossTextButton(onClick = {
                if (model.signOutApp()) {
                    preferences.edit().clear().commit(); model.appIdentityChanged(); profile = null; inside = false; account = false
                    scope.launch { runCatching { GoogleIdentity.clear(context) } }
                }
            }, enabled = !state.actionBusy && !state.busy) { Text("Sign out of app") }
        }, dismissButton = { CossTextButton(onClick = { account = false }) { Text("Keep signed in") } })
    }
}
