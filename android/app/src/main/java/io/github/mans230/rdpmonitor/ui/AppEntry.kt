package io.github.mans230.rdpmonitor.ui

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
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

internal enum class EntryPage { Welcome, SignIn, Servers, Account, Connection }
internal fun visibleEntryPage(page: EntryPage, hasAccount: Boolean, fixture: Boolean = false): EntryPage = when {
    fixture -> page
    !hasAccount -> if (page == EntryPage.SignIn) EntryPage.SignIn else EntryPage.Welcome
    page == EntryPage.SignIn -> EntryPage.Servers
    else -> page
}

/** Google identifies the local workspace; only the existing Passkey/PKCE protocol grants server access. */
@Composable fun AppEntry(model: RdpViewModel, openBrowser: (String) -> Unit,
    signIn: suspend (Context, String) -> GoogleProfile = GoogleIdentity::signIn) {
    val context = LocalContext.current
    val preferences = remember { context.getSharedPreferences("app_identity", Context.MODE_PRIVATE) }
    var profile by remember { mutableStateOf(preferences.getString("subject", null)?.takeIf { it.isNotBlank() && it == preferences.getString("connector_owner", null) }?.let { GoogleProfile(it, preferences.getString("email", "").orEmpty(), preferences.getString("name", "").orEmpty()) }) }
    val state by model.state.collectAsStateWithLifecycle()
    var page by key("account-entry-route-v2") { rememberSaveable { mutableStateOf(if (model.hasPendingPairing()) EntryPage.Connection else EntryPage.Welcome) } }
    var workspaceShell by key("account-shell-v1") { rememberSaveable { mutableStateOf(false) } }
    var signingIn by remember { mutableStateOf(false) }
    var message by rememberSaveable { mutableStateOf<String?>(null) }
    var account by rememberSaveable { mutableStateOf(false) }
    var signInJob by remember { mutableStateOf<Job?>(null) }
    var signInGeneration by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    var hadSnapshot by remember { mutableStateOf(false) }
    LaunchedEffect(state.snapshot != null, state.pairingUrl) {
        if (state.snapshot != null && !hadSnapshot || state.pairingUrl != null) page = EntryPage.Connection
        else if (hadSnapshot && state.snapshot == null && !state.busy) page = EntryPage.Servers
        hadSnapshot = state.snapshot != null
        if (state.snapshot != null) workspaceShell = true
    }
    fun leaveConnection() { if (!state.busy && !state.actionBusy) { model.cancelPairing(); model.closeConnections(); workspaceShell = true; page = EntryPage.Servers; message = null } }
    BackHandler(enabled = signingIn) { signInGeneration++; signInJob?.cancel(); signingIn = false; message = null }
    BackHandler(enabled = !signingIn && !state.busy && !state.actionBusy && page == EntryPage.Connection && state.snapshot == null) { leaveConnection() }
    fun backFromWorkspace() { page = if (state.snapshot != null) EntryPage.Connection else if (page == EntryPage.Account) EntryPage.Servers else EntryPage.Welcome; message = null }
    BackHandler(enabled = !signingIn && page in setOf(EntryPage.SignIn, EntryPage.Servers, EntryPage.Account)) { backFromWorkspace() }
    fun authenticate() {
        if (page != EntryPage.SignIn || profile != null || signingIn || state.busy || state.actionBusy) return
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
                profile = identity
                workspaceShell = model.state.value.profiles.isNotEmpty()
                page = if (model.state.value.profiles.isEmpty()) EntryPage.Connection else EntryPage.Servers
            } catch (_: GetCredentialCancellationException) { message = "Sign-in cancelled. Try again." }
            catch (_: NoCredentialException) { message = "Add a Google account to this device, then try again." }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { message = "Couldn't sign in. Check your connection and try again." }
            finally { if (generation == signInGeneration) signingIn = false }
        }
    }
    CompositionLocalProvider(LocalOnboardingBack provides ::leaveConnection, LocalAppAccount provides { page = EntryPage.Account },
        LocalServerWorkspace provides { if (!state.busy && !state.actionBusy) { model.cancelPairing(); model.closeConnections(); page = EntryPage.Servers } }) {
        Box(Modifier.fillMaxSize()) {
            // Restored navigation is not proof of account ownership.
            val visiblePage = visibleEntryPage(page, profile != null, state.demo)
            when (visiblePage) {
                EntryPage.Welcome -> WelcomePage {
                    page = if (profile == null) EntryPage.SignIn else EntryPage.Servers
                    workspaceShell = profile != null
                    message = null
                }
                EntryPage.SignIn -> GoogleSignInPage({ page = EntryPage.Welcome; message = null }, ::authenticate,
                    !signingIn && BuildConfig.GOOGLE_WEB_CLIENT_ID.isNotBlank(), message ?: if (BuildConfig.GOOGLE_WEB_CLIENT_ID.isBlank()) "Sign-in is unavailable in this build." else null)
                EntryPage.Servers, EntryPage.Account -> {
                    val content: @Composable () -> Unit = {
                        if (page == EntryPage.Account) AccountContent(profile?.name.orEmpty(), profile?.email.orEmpty(),
                            onServers = { page = EntryPage.Servers }, onSignOut = { account = true })
                        else ServerWorkspaceContent(state, model,
                            onAdd = { model.startNewServer(); page = EntryPage.Connection },
                            onReconnect = { model.connectSaved(it); page = EntryPage.Connection })
                    }
                    if (workspaceShell) RdpApp(model, openBrowser, content, workspaceKey = page.name, showShell = true, workspaceBack = ::backFromWorkspace) { page = EntryPage.Connection }
                    else OnboardingScaffold(onBack = ::backFromWorkspace, actions = {
                        if (page == EntryPage.Servers) MotionIconButton(onClick = { page = EntryPage.Account }, modifier = Modifier.size(44.dp)) {
                            Icon(androidx.compose.material.icons.Icons.Outlined.AccountCircle, "Account")
                        }
                    }) { OnboardingBody { Spacer(Modifier.height(24.dp)); content() } }
                }
                EntryPage.Connection -> RdpApp(model, openBrowser, showShell = workspaceShell)
            }
            if (signingIn) LoadingPage("Signing in", "Choose your Google account.")
            else if (page == EntryPage.Connection && state.busy && state.snapshot == null) LoadingPage("Connecting", state.selected?.name.orEmpty())
            if (account) CossDialog(onDismissRequest = { account = false }, title = { Text("Sign out of RDPMonitor?") }, text = {
                Text(profile?.email.orEmpty())
                Text("Ends this app's server sessions. Saved servers stay with this account on this device.")
            }, confirmButton = {
                CossButton(onClick = {
                    if (model.signOutApp()) {
                        preferences.edit().clear().commit(); model.appIdentityChanged(); profile = null; workspaceShell = false; page = EntryPage.Welcome; account = false
                        scope.launch { runCatching { GoogleIdentity.clear(context) } }
                    }
                }, enabled = !state.actionBusy && !state.busy, modifier = Modifier.fillMaxWidth().testTag("confirm-account-signout")) { Text("Sign out") }
            }, dismissButton = { CossOutlinedButton(onClick = { account = false }, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } })
        }
    }
}
