package io.github.mans230.rdpmonitor

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.core.network.PanelApi
import io.github.mans230.rdpmonitor.core.security.*
import io.github.mans230.rdpmonitor.core.storage.DeviceStore
import io.github.mans230.rdpmonitor.data.DemoData
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import io.github.mans230.rdpmonitor.feature.more.Tool

enum class Destination(val title: String) { Overview("Overview"), Bandwidth("Bandwidth"), Activity("Activity"), More("More") }
data class ToolReview(val tool: Tool, val payload: JsonObject, val profileId: String, val nonce: String, val createdAt: Long)
data class AppState(val profiles: List<ServerProfile> = emptyList(), val selected: ServerProfile? = null,
    val demo: Boolean = false, val snapshot: Snapshot? = null, val destination: Destination = Destination.Overview,
    val busy: Boolean = false, val message: String? = null, val connected: Boolean = false,
    val documents: Map<String, JsonElement> = emptyMap(), val documentErrors: Map<String, String> = emptyMap(),
    val documentLoading: Boolean = false, val actionBusy: Boolean = false, val review: ToolReview? = null,
    val actionResult: JsonElement? = null, val administration: Boolean = false, val connectionScreen: Boolean = false,
    val requestedScope: String = "monitoring:read", val pairingCode: String? = null, val pairingUrl: String? = null,
    val operationTitle: String = "Operation", val operationServer: String = "", val operationVisible: Boolean = false,
    val diagnostics: Set<String> = emptySet(), val editingTool: Tool? = null, val formValues: Map<String, String> = emptyMap(),
    val diagnosticOp: String = "diagnose", val diagnosticArgument: String = "", val readingsStale: Boolean = false,
    val pairingExpiresAt: Long = 0)

class RdpViewModel(application: Application): AndroidViewModel(application) {
    private val store = DeviceStore(application)
    private val api = PanelApi()
    private val _state = MutableStateFlow(AppState(profiles = store.profiles()))
    val state = _state.asStateFlow()
    private var refreshJob: Job? = null
    private var documentJob: Job? = null
    private var documentGeneration = 0
    private val diagnosticJobs = mutableMapOf<String, Job>()
    private var foreground = false
    init {
        val pending = store.pending()
        if (pending != null && System.currentTimeMillis() - pending.createdAt in 0..600_000) {
            val profile = store.profiles().firstOrNull { it.id == pending.profileId && it.origin == pending.origin }
            if (profile != null) _state.update { it.copy(selected = profile, requestedScope = pending.scope,
                pairingCode = BrowserPairing.matchCode(BrowserPairing.challenge(pending.verifier)), pairingUrl = store.pendingUrl(), pairingExpiresAt = pending.createdAt + 600_000) }
        } else { store.pending(null); store.pendingUrl(null) }
    }

    fun preview() {
        if (_state.value.actionBusy) return
        cancelPairing(); refreshJob?.cancel(); documentJob?.cancel(); documentGeneration++
        diagnosticJobs.values.forEach { it.cancel() }; diagnosticJobs.clear()
        _state.value = AppState(profiles = store.profiles(), demo = true, snapshot = DemoData.snapshot())
    }
    fun appIdentityChanged() {
        refreshJob?.cancel(); documentJob?.cancel(); documentGeneration++
        diagnosticJobs.values.forEach { it.cancel() }; diagnosticJobs.clear()
        _state.value = AppState(profiles = store.profiles())
    }
    fun signOutApp(): Boolean {
        if (_state.value.actionBusy || _state.value.busy) return false
        cancelPairing()
        val sessions = store.profiles().mapNotNull { profile -> store.session(profile.id)?.let { profile to it } }
        store.clearSessions()
        appIdentityChanged()
        viewModelScope.launch { sessions.forEach { (profile, session) -> api.logout(profile, session) } }
        return true
    }
    fun connectScreen() { refreshJob?.cancel(); documentJob?.cancel(); documentGeneration++; _state.update { it.copy(connectionScreen = true, message = null, documents = emptyMap(), documentErrors = emptyMap(), review = null, actionResult = null, operationVisible = false, editingTool = null, formValues = emptyMap(), documentLoading = false) } }
    fun closeConnections() { _state.update { it.copy(connectionScreen = false) }; foreground(foreground) }
    fun destination(value: Destination) { _state.update { it.copy(destination = value, editingTool = null, formValues = emptyMap()) } }
    fun chooseScope(scope: String) { if (scope !in setOf("monitoring:read", "administration")) return; cancelPairing(); _state.update { it.copy(requestedScope = scope) } }
    fun cancelPairing() { store.pending(null); store.pendingUrl(null); _state.update { it.copy(pairingCode = null, pairingUrl = null, pairingExpiresAt = 0, message = null) } }
    fun expirePairing() {
        if (_state.value.pairingUrl != null && System.currentTimeMillis() >= _state.value.pairingExpiresAt) {
            cancelPairing(); _state.update { it.copy(message = "Approval expired. Connect again.") }
        }
    }
    fun reconnect(management: Boolean = false) {
        val profile = _state.value.selected ?: return
        val scope = if (management) "administration" else store.session(profile.id)?.scope ?: _state.value.requestedScope
        _state.update { it.copy(requestedScope = scope, connectionScreen = true) }
        connect(profile.name, profile.origin, forcePair = true)
    }
    fun editTool(tool: Tool, initial: Map<String, String>) { _state.update { it.copy(editingTool = tool, formValues = tool.fields.associate { field -> field.key to initial[field.key].orEmpty() }) } }
    fun updateForm(key: String, value: String) { _state.update { it.copy(formValues = it.formValues + (key to value)) } }
    fun closeForm() { _state.update { it.copy(editingTool = null, formValues = emptyMap()) } }
    fun dismissOperation() { if (!_state.value.actionBusy) _state.update { it.copy(operationVisible = false, actionResult = null) } }
    fun showOperation() { _state.update { it.copy(operationVisible = true) } }
    fun hideOperation() { _state.update { it.copy(operationVisible = false) } }
    fun diagnosticInput(op: String, argument: String) { _state.update { it.copy(diagnosticOp = op, diagnosticArgument = argument) } }
    fun remove(profile: ServerProfile) {
        store.remove(profile.id)
        _state.update { state -> val active = state.selected?.id == profile.id
            state.copy(profiles = store.profiles(), selected = if (active) null else state.selected,
                snapshot = if (active) null else state.snapshot, connected = state.connected && !active, message = null)
        }
    }
    fun clearMessage() { _state.update { it.copy(message = null) } }

    fun connect(name: String, input: String, forcePair: Boolean = false) {
        if (_state.value.busy || _state.value.actionBusy) return
        val scope = _state.value.requestedScope
        val origin = runCatching { PrivateOrigin.parse(input) }.getOrElse {
            _state.update { state -> state.copy(message = it.message ?: "Check the private server address.") }; return
        }
        if (name.trim().length !in 1..60) { _state.update { it.copy(message = "Enter a server name (1–60 characters).") }; return }
        val profile = store.profiles().firstOrNull { it.origin == origin }?.copy(name = name.trim())
            ?: ServerProfile(name = name.trim(), origin = origin)
        store.save(profile)
        cancelPairing()
        documentJob?.cancel(); documentGeneration++
        diagnosticJobs.values.forEach { it.cancel() }; diagnosticJobs.clear()
        viewModelScope.launch {
            _state.update { it.copy(profiles = store.profiles(), selected = profile, snapshot = null, demo = false, connected = false, busy = true, message = null,
                documents = emptyMap(), documentErrors = emptyMap(), actionResult = null, review = null, diagnostics = emptySet(), documentLoading = false,
                operationVisible = false, editingTool = null, formValues = emptyMap()) }
            try {
                when (val health = api.health(profile)) {
                    is DataResult.Ready -> {
                        val session = store.session(profile.id)
                        if (!forcePair && session != null && session.scope == scope && session.origin == profile.origin && session.expiresAt > System.currentTimeMillis()) {
                            refresh(profile)
                        } else if (!health.value.pairingAvailable) {
                            _state.update { it.copy(message = "Update the server suite to enable app pairing.") }
                        } else when (val launch = api.beginPairing(profile, scope)) {
                            is DataResult.Ready -> {
                                store.pending(launch.value.pending)
                                store.pendingUrl(launch.value.url)
                                val code = BrowserPairing.matchCode(BrowserPairing.challenge(launch.value.pending.verifier))
                                _state.update { it.copy(pairingCode = code, pairingUrl = launch.value.url, message = null, pairingExpiresAt = launch.value.pending.createdAt + 600_000) }
                            }
                            else -> _state.update { it.copy(message = "App pairing is unavailable on this server.") }
                        }
                    }
                    is DataResult.Failed -> _state.update { it.copy(message = health.message) }
                    else -> _state.update { it.copy(message = "Sign-in is required.") }
                }
            } finally { _state.update { it.copy(busy = false, connectionScreen = !it.connected) }; foreground(foreground) }
        }
    }
    fun hasPendingPairing() = store.pending() != null
    fun callback(uri: String) {
        val pending = store.pending()
        val parsed = runCatching { BrowserPairing.callback(uri, pending, System.currentTimeMillis()) }.getOrElse {
            _state.update { state -> state.copy(message = it.message ?: "Invalid sign-in response.") }; return
        }
        store.pending(null) // One callback attempt; a failed exchange starts a fresh sign-in.
        store.pendingUrl(null)
        val profile = store.profiles().firstOrNull { it.id == parsed.pending.profileId && it.origin == parsed.pending.origin }
            ?: run { _state.update { it.copy(message = "The server profile changed. Start sign-in again.") }; return }
        viewModelScope.launch {
            _state.update { it.copy(busy = true, selected = profile, demo = false, snapshot = null, connected = false, pairingCode = null, pairingUrl = null) }
            try {
                when (val result = api.exchange(parsed)) {
                    is DataResult.Ready -> { store.session(result.value); refresh(profile) }
                    is DataResult.Failed -> _state.update { it.copy(message = result.message) }
                    else -> _state.update { it.copy(message = "App sign-in could not be completed.") }
                }
            } finally { _state.update { it.copy(busy = false, connectionScreen = !it.connected) }; foreground(foreground) }
        }
    }
    private suspend fun refresh(profile: ServerProfile) {
        val session = store.session(profile.id) ?: return
        if (session.expiresAt <= System.currentTimeMillis()) {
            store.clearSession(profile.id)
            _state.update { it.sessionEnded() }
            return
        }
        when (val result = api.snapshot(profile, session)) {
            is DataResult.Ready -> {
                if (_state.value.demo || _state.value.selected?.id != profile.id || store.session(profile.id)?.cookie != session.cookie) return
                store.session(session.copy(expiresAt = System.currentTimeMillis() + session.idleSeconds * 1000L))
                _state.update { it.copy(snapshot = result.value, demo = false, connected = true, readingsStale = false, message = null, administration = session.scope == "administration") }
            }
            DataResult.SignInRequired -> { store.clearSession(profile.id); _state.update { it.sessionEnded() } }
            is DataResult.Failed -> _state.update { it.copy(message = result.message, readingsStale = true) }
            else -> Unit
        }
    }
    fun refresh() { if (_state.value.demo) return; _state.value.selected?.let { viewModelScope.launch { refresh(it) } } }
    fun loadDocuments(paths: List<String>) {
        if (_state.value.demo) return
        if (paths.size == 1 && paths[0].startsWith("/api/diag?")) { loadDiagnostic(paths[0]); return }
        val profile = _state.value.selected ?: return
        val session = store.session(profile.id) ?: return
        val generation = ++documentGeneration
        documentJob?.cancel()
        documentJob = viewModelScope.launch {
            _state.update { it.copy(documentLoading = true) }
            try {
                val results = coroutineScope { paths.distinct().map { path -> async { path to api.document(profile, session, path) } }.awaitAll() }
                if (generation != documentGeneration || _state.value.selected?.id != profile.id || _state.value.demo) return@launch
                _state.update { current ->
                    val docs = current.documents.toMutableMap(); val errors = current.documentErrors.toMutableMap()
                    results.forEach { (path, result) -> when (result) {
                        is DataResult.Ready -> { docs[path] = result.value; errors.remove(path) }
                        is DataResult.Failed -> errors[path] = result.message
                        else -> errors[path] = "Session expired. Reconnect to sign in."
                    } }
                    current.copy(documents = docs, documentErrors = errors)
                }
            } finally { if (generation == documentGeneration) _state.update { it.copy(documentLoading = false) } }
        }
    }
    private fun loadDiagnostic(path: String) {
        if (diagnosticJobs[path]?.isActive == true || _state.value.demo) return
        val profile = _state.value.selected ?: return
        val session = store.session(profile.id) ?: return
        diagnosticJobs[path] = viewModelScope.launch {
            _state.update { it.copy(diagnostics = it.diagnostics + path, documentErrors = it.documentErrors - path) }
            try {
                val result = api.document(profile, session, path)
                if (_state.value.selected?.id != profile.id || _state.value.demo) return@launch
                _state.update { when (result) {
                    is DataResult.Ready -> it.copy(documents = it.documents + (path to result.value))
                    is DataResult.Failed -> it.copy(documentErrors = it.documentErrors + (path to result.message))
                    else -> it.copy(documentErrors = it.documentErrors + (path to "Sign in again to run this diagnostic."))
                } }
            } finally { if (_state.value.selected?.id == profile.id) _state.update { it.copy(diagnostics = it.diagnostics - path) } }
        }
    }
    fun review(tool: Tool, payload: JsonObject) {
        if (_state.value.demo || _state.value.actionBusy) return
        val profile = _state.value.selected ?: return
        val session = store.session(profile.id)?.takeIf { it.scope == "administration" } ?: return
        if (tool.action == "mobile_revoke") {
            _state.update { it.copy(review = ToolReview(tool, payload, profile.id, "local", System.currentTimeMillis())) }; return
        }
        viewModelScope.launch {
            _state.update { it.copy(actionBusy = true, actionResult = null, operationTitle = "Preparing ${tool.title}", operationServer = profile.name, operationVisible = true) }
            try {
                val prepare = JsonObject(payload.filterKeys { it != "action" } + mapOf("action" to JsonPrimitive("prepare"), "target" to JsonPrimitive(tool.action)))
                when (val result = api.action(profile, session, prepare)) {
                    is DataResult.Ready -> {
                        val nonce = result.value["nonce"]?.jsonPrimitive?.content
                        if (nonce != null && _state.value.connected && _state.value.selected?.id == profile.id && !_state.value.demo)
                            _state.update { it.copy(review = ToolReview(tool, payload, profile.id, nonce, System.currentTimeMillis()), operationVisible = false) }
                    }
                    is DataResult.Failed -> _state.update { it.copy(actionResult = buildJsonObject { put("error", result.message) }) }
                    else -> _state.update { it.copy(actionResult = buildJsonObject { put("error", "Reconnect to sign in again.") }) }
                }
            } finally { _state.update { it.copy(actionBusy = false) } }
        }
    }
    fun cancelReview() { _state.update { it.copy(review = null) } }
    fun confirmAction() {
        val review = _state.value.review ?: return
        _state.update { it.copy(review = null) }
        val profile = _state.value.selected?.takeIf { it.id == review.profileId } ?: return
        val session = store.session(profile.id)?.takeIf { it.scope == "administration" } ?: return
        if (_state.value.demo || _state.value.actionBusy) return
        if (System.currentTimeMillis() - review.createdAt > 55_000) {
            _state.update { it.copy(actionResult = buildJsonObject { put("error", "Confirmation expired. Review the operation again.") }, operationTitle = review.tool.title, operationServer = profile.name, operationVisible = true) }; return
        }
        viewModelScope.launch {
            _state.update { it.copy(actionBusy = true, operationTitle = review.tool.title, operationServer = profile.name, operationVisible = true, actionResult = null) }
            try {
                val body = JsonObject(review.payload + ("nonce" to JsonPrimitive(review.nonce)))
                when (val result = api.action(profile, session, body)) {
                    is DataResult.Ready -> _state.update { it.copy(actionResult = result.value) }
                    is DataResult.Failed -> _state.update { it.copy(actionResult = buildJsonObject { put("error", result.message) }) }
                    else -> _state.update { it.copy(actionResult = buildJsonObject { put("error", "Session expired. Reconnect.") }) }
                }
            } finally { _state.update { it.copy(actionBusy = false) } }
        }
    }
    fun disconnect() {
        val profile = _state.value.selected ?: return
        if (_state.value.busy) return
        refreshJob?.cancel()
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            var message = "Disconnected. Your saved server address is kept."
            try {
                store.session(profile.id)?.let { session ->
                    if (session.expiresAt > System.currentTimeMillis()) {
                        val result = api.logout(profile, session)
                        if (result is DataResult.Failed) message = result.message
                    }
                }
            } finally {
                store.clearSession(profile.id); store.pending(null); store.pendingUrl(null)
                _state.update { it.copy(snapshot = null, connected = false, busy = false, connectionScreen = false, message = message) }
            }
        }
    }
    fun foreground(active: Boolean) {
        foreground = active; refreshJob?.cancel()
        if (active && _state.value.connected && !_state.value.demo) refreshJob = viewModelScope.launch {
            while (isActive && _state.value.connected && !_state.value.demo) { _state.value.selected?.let { refresh(it) }; delay(5_000) }
        }
    }
}
