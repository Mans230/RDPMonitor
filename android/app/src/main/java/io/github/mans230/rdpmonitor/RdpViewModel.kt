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
    val actionResult: JsonElement? = null, val administration: Boolean = false, val connectionScreen: Boolean = false)

class RdpViewModel(application: Application): AndroidViewModel(application) {
    private val store = DeviceStore(application)
    private val api = PanelApi()
    private val _state = MutableStateFlow(AppState(profiles = store.profiles()))
    val state = _state.asStateFlow()
    private var refreshJob: Job? = null
    private var documentJob: Job? = null
    private var documentGeneration = 0
    private var foreground = false

    fun preview() { refreshJob?.cancel(); documentJob?.cancel(); documentGeneration++; _state.update { it.copy(selected = null, demo = true, snapshot = DemoData.snapshot(), message = null, connected = false, documents = emptyMap(), documentErrors = emptyMap(), review = null, actionResult = null, administration = false, documentLoading = false, connectionScreen = false) } }
    fun connectScreen() { refreshJob?.cancel(); documentJob?.cancel(); documentGeneration++; _state.update { it.copy(connectionScreen = true, message = null, documents = emptyMap(), documentErrors = emptyMap(), review = null, actionResult = null, documentLoading = false) } }
    fun closeConnections() { _state.update { it.copy(connectionScreen = false) }; foreground(foreground) }
    fun destination(value: Destination) { _state.update { it.copy(destination = value) } }
    fun remove(profile: ServerProfile) {
        store.remove(profile.id)
        _state.update { state -> val active = state.selected?.id == profile.id
            state.copy(profiles = store.profiles(), selected = if (active) null else state.selected,
                snapshot = if (active) null else state.snapshot, connected = state.connected && !active, message = null)
        }
    }
    fun clearMessage() { _state.update { it.copy(message = null) } }

    fun connect(name: String, input: String, openBrowser: (String) -> Unit) {
        if (_state.value.busy) return
        val origin = runCatching { PrivateOrigin.parse(input) }.getOrElse {
            _state.update { state -> state.copy(message = it.message ?: "Check the private server address.") }; return
        }
        if (name.trim().length !in 1..60) { _state.update { it.copy(message = "Enter a server name (1–60 characters).") }; return }
        val profile = store.profiles().firstOrNull { it.origin == origin }?.copy(name = name.trim())
            ?: ServerProfile(name = name.trim(), origin = origin)
        store.save(profile)
        viewModelScope.launch {
            _state.update { it.copy(profiles = store.profiles(), selected = profile, snapshot = null, demo = false, connected = false, busy = true, message = null) }
            try {
                when (val health = api.health(profile)) {
                    is DataResult.Ready -> {
                        val session = store.session(profile.id)
                        if (session != null && session.scope == "administration" && session.origin == profile.origin && session.expiresAt > System.currentTimeMillis()) {
                            refresh(profile)
                        } else if (!health.value.pairingAvailable) {
                            _state.update { it.copy(message = "Server reachable. Native app pairing is not enabled on this server yet. You can open the secure web panel below.") }
                        } else when (val launch = api.beginPairing(profile)) {
                            is DataResult.Ready -> {
                                store.pending(launch.value.pending)
                                val code = BrowserPairing.matchCode(BrowserPairing.challenge(launch.value.pending.verifier))
                                _state.update { it.copy(message = "Pairing code: $code. Match this code in the browser before approving monitoring access.") }
                                openBrowser(launch.value.url)
                            }
                            else -> _state.update { it.copy(message = "This server cannot pair the native app yet. Open the secure web panel to continue.") }
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
        val profile = store.profiles().firstOrNull { it.id == parsed.pending.profileId && it.origin == parsed.pending.origin }
            ?: run { _state.update { it.copy(message = "The server profile changed. Start sign-in again.") }; return }
        viewModelScope.launch {
            _state.update { it.copy(busy = true, selected = profile, demo = false, snapshot = null, connected = false) }
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
            _state.update { it.copy(connected = false, message = "Your session ended. Connect again to sign in.") }
            return
        }
        when (val result = api.snapshot(profile, session)) {
            is DataResult.Ready -> {
                if (_state.value.demo || _state.value.selected?.id != profile.id || store.session(profile.id)?.cookie != session.cookie) return
                store.session(session.copy(expiresAt = System.currentTimeMillis() + session.idleSeconds * 1000L))
                _state.update { it.copy(snapshot = result.value, demo = false, connected = true, message = null, administration = session.scope == "administration") }
            }
            DataResult.SignInRequired -> { store.clearSession(profile.id); _state.update { it.copy(connected = false, message = "Your session ended. Connect again to sign in.") } }
            is DataResult.Failed -> _state.update { it.copy(message = result.message) }
            else -> Unit
        }
    }
    fun refresh() { if (_state.value.demo) return; _state.value.selected?.let { viewModelScope.launch { refresh(it) } } }
    fun loadDocuments(paths: List<String>) {
        if (_state.value.demo) return
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
    fun review(tool: Tool, payload: JsonObject) {
        if (_state.value.demo || _state.value.actionBusy) return
        val profile = _state.value.selected ?: return
        val session = store.session(profile.id)?.takeIf { it.scope == "administration" } ?: return
        if (tool.action == "mobile_revoke") {
            _state.update { it.copy(review = ToolReview(tool, payload, profile.id, "local", System.currentTimeMillis())) }; return
        }
        viewModelScope.launch {
            _state.update { it.copy(actionBusy = true, actionResult = null) }
            try {
                val prepare = JsonObject(payload.filterKeys { it != "action" } + mapOf("action" to JsonPrimitive("prepare"), "target" to JsonPrimitive(tool.action)))
                when (val result = api.action(profile, session, prepare)) {
                    is DataResult.Ready -> {
                        val nonce = result.value["nonce"]?.jsonPrimitive?.content
                        if (nonce != null && _state.value.connected && _state.value.selected?.id == profile.id && !_state.value.demo)
                            _state.update { it.copy(review = ToolReview(tool, payload, profile.id, nonce, System.currentTimeMillis())) }
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
            _state.update { it.copy(actionResult = buildJsonObject { put("error", "Confirmation expired. Review the operation again.") }) }; return
        }
        viewModelScope.launch {
            _state.update { it.copy(actionBusy = true) }
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
                store.clearSession(profile.id); store.pending(null)
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
