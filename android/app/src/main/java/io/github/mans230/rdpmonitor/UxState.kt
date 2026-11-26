package io.github.mans230.rdpmonitor

enum class RootBack { System, Tools, Overview }
fun rootBack(hasDetail: Boolean, destination: Destination): RootBack = when {
    hasDetail -> RootBack.Tools
    destination != Destination.Overview -> RootBack.Overview
    else -> RootBack.System
}
fun AppState.sessionEnded() = copy(connected = false, administration = false, readingsStale = true, review = null,
    message = "Your session ended. Sign in again to resume live readings.")
