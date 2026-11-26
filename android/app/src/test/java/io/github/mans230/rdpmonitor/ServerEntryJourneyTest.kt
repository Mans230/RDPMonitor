package io.github.mans230.rdpmonitor

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import io.github.mans230.rdpmonitor.core.model.ServerProfile
import io.github.mans230.rdpmonitor.feature.connect.*
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ServerEntryJourneyTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    @Test fun validatesBeforeCallingTheRealConnectionBoundary() {
        val model = ViewModelProvider(ui.activity, ViewModelProvider.AndroidViewModelFactory(ui.activity.application))[RdpViewModel::class.java]
        var submitted: Pair<String, String>? = null
        ui.setContent { RdpTheme { ConnectScreen(AppState(), model, {}, connect = { name, url -> submitted = name to url }) } }
        ui.onNodeWithText("Connect server").performClick()
        ui.onNodeWithText("Enter a server name.").assertExists()
        ui.onNodeWithContentDescription("Server name").performTextInput(" Work ")
        ui.onNodeWithContentDescription("Server address").performTextInput("http://work.tailnet.ts.net")
        ui.onNodeWithText("Connect server").performClick()
        ui.runOnIdle { assertNull(submitted) }
        ui.onNodeWithContentDescription("Server address").performTextReplacement("https://work.tailnet.ts.net")
        ui.onNodeWithText("Connect server").performClick()
        ui.runOnIdle { assertEquals("Work" to "https://work.tailnet.ts.net", submitted); assertFalse(model.state.value.connected) }
    }
    @Test fun approvalCodeAndScopeRemainVisibleBeforeBrowserLaunch() {
        val model = ViewModelProvider(ui.activity, ViewModelProvider.AndroidViewModelFactory(ui.activity.application))[RdpViewModel::class.java]
        val url = "https://work.tailnet.ts.net/mobile/approve"
        var opened: String? = null
        val state = AppState(selected = ServerProfile(name = "Work", origin = "https://work.tailnet.ts.net"),
            pairingCode = "ABCD-1234", pairingUrl = url, pairingExpiresAt = System.currentTimeMillis() + 600000, requestedScope = "administration")
        ui.setContent { RdpTheme { ConnectScreen(state, model, { opened = it }) } }
        ui.onNodeWithText("ABCD-1234").performScrollTo().assertIsDisplayed()
        ui.onNodeWithText("Administration").assertExists()
        ui.runOnIdle { assertNull(opened); assertFalse(model.state.value.connected) }
        ui.onNodeWithText("Continue in browser").assertIsDisplayed().performClick()
        ui.runOnIdle { assertEquals(url, opened); assertFalse(model.state.value.connected) }
    }
    @Test fun secretBearingOrPublicAddressesNeverPassTheFormBoundary() {
        listOf("http://work.tailnet.ts.net", "https://user:secret@work.tailnet.ts.net", "https://work.tailnet.ts.net/?token=secret", "https://199.47.241.111").forEach {
            val error = serverFormError("Work", it)
            assertNotNull(error); assertFalse(error!!.contains("secret"))
        }
        assertNotNull(serverFormError(" ", "https://work.tailnet.ts.net"))
        assertNull(serverFormError("Work", "https://work.tailnet.ts.net"))
    }
}
