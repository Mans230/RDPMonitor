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

enum class Destination(val title: String) { Overview("Overview"), Bandwidth("Bandwidth"), Activity("Activity"), More("More") }
data class AppState(val profiles: List<ServerProfile> = emptyList(), val selected: ServerProfile? = null,
    val demo: Boolean = false, val snapshot: Snapshot? = null, val destination: Destination = Destination.Overview,
    val busy: Boolean = false, val message: String? = null, val connected: Boolean = false)

class RdpViewModel(application: Application): AndroidViewModel(application) {
    private val store = DeviceStore(application)
    private val api = PanelApi()
    private val _state = MutableStateFlow(AppState(profiles = store.profiles()))
    val state = _state.asStateFlow()
    private var refreshJob: Job? = null
    private var foreground = false

    fun preview() { refreshJob?.cancel(); _state.update { it.copy(selected = null, demo = true, snapshot = DemoData.snapshot(), message = null, connected = false) } }
    fun connectScreen() { refreshJob?.cancel(); _state.update { it.copy(demo = false, snapshot = null, connected = false, message = null) } }
    fun destination(value: Destination) { _state.update { it.copy(destination = value) } }
    fun remove(profile: ServerProfile) { store.remove(profile.id); _state.update { it.copy(profiles = store.profiles(), selected = null, message = null) } }
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
            _state.update { it.copy(profiles = store.profiles(), selected = profile, busy = true, message = null) }
            try {
                when (val health = api.health(profile)) {
                    is DataResult.Ready -> {
                        val session = store.session(profile.id)
                        if (session != null && session.origin == profile.origin && session.expiresAt > System.currentTimeMillis()) {
                            refresh(profile)
                        } else if (!health.value.pairingAvailable) {
                            _state.update { it.copy(message = "Server reachable. Native app pairing is not enabled on this server yet. You can open the secure web panel below.") }
                        } else when (val launch = api.beginPairing(profile)) {
                            is DataResult.Ready -> { store.pending(launch.value.pending); openBrowser(launch.value.url) }
                            else -> _state.update { it.copy(message = "This server cannot pair the native app yet. Open the secure web panel to continue.") }
                        }
                    }
                    is DataResult.Failed -> _state.update { it.copy(message = health.message) }
                    else -> _state.update { it.copy(message = "Sign-in is required.") }
                }
            } finally { _state.update { it.copy(busy = false) }; foreground(foreground) }
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
            _state.update { it.copy(busy = true, selected = profile, demo = false) }
            try {
                when (val result = api.exchange(parsed)) {
                    is DataResult.Ready -> { store.session(result.value); refresh(profile) }
                    is DataResult.Failed -> _state.update { it.copy(message = result.message) }
                    else -> _state.update { it.copy(message = "App sign-in could not be completed.") }
                }
            } finally { _state.update { it.copy(busy = false) }; foreground(foreground) }
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
                store.session(session.copy(expiresAt = System.currentTimeMillis() + session.idleSeconds * 1000L))
                _state.update { it.copy(snapshot = result.value, demo = false, connected = true, message = null) }
            }
            DataResult.SignInRequired -> { store.clearSession(profile.id); _state.update { it.copy(connected = false, message = "Your session ended. Connect again to sign in.") } }
            is DataResult.Failed -> _state.update { it.copy(message = result.message) }
            else -> Unit
        }
    }
    fun refresh() { if (_state.value.demo) return; _state.value.selected?.let { viewModelScope.launch { refresh(it) } } }
    fun foreground(active: Boolean) {
        foreground = active; refreshJob?.cancel()
        if (active && _state.value.connected && !_state.value.demo) refreshJob = viewModelScope.launch {
            while (isActive && _state.value.connected && !_state.value.demo) { _state.value.selected?.let { refresh(it) }; delay(5_000) }
        }
    }
}
