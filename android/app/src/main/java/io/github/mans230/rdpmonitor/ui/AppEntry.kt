package io.github.mans230.rdpmonitor.ui

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.NoCredentialException
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.core.security.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.ensureActive

/** Google identifies the local workspace; only the existing Passkey/PKCE protocol grants server access. */
@Composable fun AppEntry(model: RdpViewModel, openBrowser: (String) -> Unit,
    signIn: suspend (Context, String) -> GoogleProfile = GoogleIdentity::signIn) {
    val context = LocalContext.current
    val preferences = remember { context.getSharedPreferences("app_identity", Context.MODE_PRIVATE) }
    var profile by remember { mutableStateOf(preferences.getString("subject", null)?.let { GoogleProfile(it, preferences.getString("email", "").orEmpty(), preferences.getString("name", "").orEmpty()) }) }
    val state by model.state.collectAsStateWithLifecycle()
    var inside by rememberSaveable { mutableStateOf(profile != null || model.hasPendingPairing()) }
    var page by rememberSaveable { mutableStateOf("welcome") }
    var signingIn by remember { mutableStateOf(false) }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var account by rememberSaveable { mutableStateOf(false) }
    var signInJob by remember { mutableStateOf<Job?>(null) }
    var signInGeneration by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(state.snapshot, state.pairingUrl, state.busy) {
        if (state.snapshot != null || state.pairingUrl != null || state.busy) inside = true
    }
    fun backToLogin() { if (!state.busy && !state.actionBusy) { model.cancelPairing(); inside = false; page = "login"; message = null } }
    BackHandler(enabled = signingIn) { signInGeneration++; signInJob?.cancel(); signingIn = false; message = null }
    BackHandler(enabled = !signingIn && !state.busy && inside && state.snapshot == null) { backToLogin() }
    BackHandler(enabled = !signingIn && !inside && page == "login") { page = "welcome"; message = null }
    fun authenticate() {
        if (signingIn || state.busy || state.actionBusy) return
        signingIn = true; message = null
        val generation = ++signInGeneration
        signInJob = scope.launch {
            try {
                val identity = signIn(context, BuildConfig.GOOGLE_WEB_CLIENT_ID)
                coroutineContext.ensureActive()
                if (generation != signInGeneration) return@launch
                // Re-authenticating the same workspace must not discard its saved server sessions.
                if (identity.subject != profile?.subject || preferences.getString("connector_owner", null) != identity.subject) {
                    if (!model.signOutApp()) { message = "Finish the current operation first."; return@launch }
                    preferences.edit().putString("connector_owner", identity.subject).putString("subject", identity.subject)
                        .putString("email", identity.email).putString("name", identity.name).commit()
                    model.appIdentityChanged()
                } else preferences.edit().putString("email", identity.email).putString("name", identity.name).commit()
                profile = identity; inside = true
            } catch (_: GetCredentialCancellationException) { message = "Sign-in cancelled. Try again." }
            catch (_: NoCredentialException) { message = "Add a Google account to this device, then try again." }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { message = "Couldn't sign in. Check your connection and try again." }
            finally { if (generation == signInGeneration) signingIn = false }
        }
    }
    CompositionLocalProvider(LocalOnboardingBack provides ::backToLogin, LocalAppAccount provides { account = true }) {
        Box(Modifier.fillMaxSize()) {
            if (!inside) {
                if (page == "welcome") WelcomePage { page = "login"; message = null }
                else GoogleSignInPage({ page = "welcome"; message = null }, ::authenticate,
                    !signingIn && BuildConfig.GOOGLE_WEB_CLIENT_ID.isNotBlank(), message ?: if (BuildConfig.GOOGLE_WEB_CLIENT_ID.isBlank()) "Sign-in is unavailable in this build." else null)
            } else RdpApp(model, openBrowser)
            if (signingIn) LoadingPage("Signing in", "Choose your Google account.")
            else if (inside && state.busy && state.snapshot == null) LoadingPage("Connecting", state.selected?.name.orEmpty())
            if (account) CossDialog(onDismissRequest = { account = false }, title = { Text(profile?.name ?: "Account") }, text = {
                Text(profile?.email.orEmpty())
            }, confirmButton = {
                CossButton(onClick = {
                    if (model.signOutApp()) {
                        preferences.edit().clear().commit(); model.appIdentityChanged(); profile = null; inside = false; page = "welcome"; account = false
                        scope.launch { runCatching { GoogleIdentity.clear(context) } }
                    }
                }, enabled = !state.actionBusy && !state.busy, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
            }, dismissButton = { CossOutlinedButton(onClick = { account = false }, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } })
        }
    }
}
