package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.data.DemoData
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.ui.EntryPage
import io.github.mans230.rdpmonitor.ui.visibleEntryPage
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class AccountStateTest {
    @Test fun restoredRoutesCannotExposeAWorkspaceWithoutItsAccountOrRepeatGoogleWithOne() {
        listOf(EntryPage.Servers, EntryPage.Account, EntryPage.Connection).forEach { route ->
            assertEquals(EntryPage.Welcome, visibleEntryPage(route, hasAccount = false))
        }
        assertEquals(EntryPage.SignIn, visibleEntryPage(EntryPage.SignIn, hasAccount = false))
        assertEquals(EntryPage.Servers, visibleEntryPage(EntryPage.SignIn, hasAccount = true))
        assertEquals(EntryPage.Welcome, visibleEntryPage(EntryPage.Welcome, hasAccount = true))
    }
    @Test fun disconnectClearsAllServerStateAndRetainsOnlySavedProfiles() {
        val profile = ServerProfile(id = "owned", name = "Work", origin = "https://work.tailnet.ts.net")
        val state = AppState(profiles = listOf(profile), selected = profile, connected = true, snapshot = DemoData.snapshot(),
            documents = mapOf("/api/audit" to JsonPrimitive("old actor")), documentErrors = mapOf("/api/setup" to "old error"),
            administration = true, actionResult = JsonPrimitive("old result"), diagnostics = setOf("old diagnostic"),
            formValues = mapOf("value" to "private field"), operationVisible = true, requestedScope = "administration",
            pairingCode = "old code", pairingUrl = "https://work.tailnet.ts.net/approve", readingsStale = true)
        assertEquals(AppState(profiles = listOf(profile)), state.disconnected())
    }
    @Test fun reconnectReusesOnlyAnUnexpiredSessionBoundToTheExactSavedServer() {
        val profile = ServerProfile(id = "owned", name = "Work", origin = "https://work.tailnet.ts.net")
        val active = AppSession(profile.id, profile.origin, "fixture", "fixture", "owner", 2000, scope = "administration")
        assertEquals("administration", savedConnectionScope(profile, active, 1000))
        assertEquals("monitoring:read", savedConnectionScope(profile, active.copy(expiresAt = 999), 1000))
        assertEquals("monitoring:read", savedConnectionScope(profile, active.copy(origin = "https://other.tailnet.ts.net"), 1000))
        assertEquals("monitoring:read", savedConnectionScope(profile, active.copy(profileId = "foreign"), 1000))
        assertEquals("monitoring:read", savedConnectionScope(profile, null, 1000))
    }
    @Test fun everyCatalogControlHasAnExplicitOwningSection() {
        Feature.entries.forEach { feature -> ToolCatalog.tools(feature).forEach { tool ->
            assertFalse(toolSection(feature, tool).isBlank())
            assertNotEquals("Actions", toolSection(feature, tool))
        } }
        assertEquals("Power controls", toolSection(Feature.Maintenance, ToolCatalog.tools(Feature.Maintenance).first { it.action == "reboot" }))
        assertEquals("Alert delivery", toolSection(Feature.Settings, ToolCatalog.tools(Feature.Settings).first { it.action == "mute" }))
    }
}
