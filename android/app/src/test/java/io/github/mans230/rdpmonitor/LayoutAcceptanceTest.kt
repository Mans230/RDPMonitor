package io.github.mans230.rdpmonitor

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.Density
import androidx.lifecycle.ViewModelProvider
import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.feature.activity.ProcessWorkspace
import io.github.mans230.rdpmonitor.ui.ServerWorkspaceContent
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import io.github.mans230.rdpmonitor.data.DemoData
import io.github.mans230.rdpmonitor.feature.more.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w320dp-h740dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class LayoutAcceptanceTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    private fun capture(name: String) {
        lateinit var bitmap: Bitmap
        ui.runOnIdle { val view = ui.activity.window.decorView; bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap)) }
        File("build/reports/app-journeys/$name.png").apply { parentFile!!.mkdirs() }.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }
    @Test fun reportRetainsUnknownFieldsRedactsSecretsAndClosesOnServerSwitch() {
        val model = ViewModelProvider(ui.activity, ViewModelProvider.AndroidViewModelFactory(ui.activity.application))[RdpViewModel::class.java]
        val state = mutableStateOf(AppState(demo = true, selected = ServerProfile(id = "a", name = "Server A", origin = "https://a.tailnet.ts.net"),
            documents = mapOf("/api/future" to buildJsonObject { put("future_measurement", 42); put("secret_token", "never-show-this") })))
        ui.setContent { RdpTheme { OnboardingScaffold { OnboardingBody { ManagementScreen(Feature.Diagnostics, state.value, model, {}, {}) } } } }
        ui.onNodeWithText("Report details").performScrollTo().performClick()
        ui.onNode(hasText("future_measurement", substring = true)).assertExists()
        ui.onNode(hasText("never-show-this", substring = true)).assertDoesNotExist()
        ui.runOnIdle { state.value = AppState(demo = true, selected = ServerProfile(id = "b", name = "Server B", origin = "https://b.tailnet.ts.net")) }
        ui.onNode(hasText("future_measurement", substring = true)).assertDoesNotExist()
        ui.onNodeWithText("Report details").assertIsNotEnabled()
    }
    @Test fun serverDirectoryAtLargeTextKeepsAddAndLastSavedServerReachable() {
        val model = ViewModelProvider(ui.activity, ViewModelProvider.AndroidViewModelFactory(ui.activity.application))[RdpViewModel::class.java]
        val profiles = (1..40).map { ServerProfile(id = "$it", name = "Work server $it", origin = "https://work-$it.tailnet.ts.net") }
        var adding = false
        ui.setContent { RdpTheme { CompositionLocalProvider(LocalDensity provides Density(1f, 1.5f)) {
            OnboardingScaffold { OnboardingBody { ServerWorkspaceContent(AppState(profiles = profiles), model, { adding = true }, {}) } }
        } } }
        ui.onNodeWithText("Add server").performScrollTo().performClick()
        ui.runOnIdle { assertTrue(adding) }
        ui.onNodeWithTag("saved-servers-list").performScrollTo()
        ui.onNodeWithTag("saved-servers-list").performScrollToNode(hasTestTag("server-40"))
        ui.onNodeWithTag("server-40").assertIsDisplayed()
        capture("320-servers-large-text-last-row")
    }
    @Test fun longProcessListAtLargeTextCanReachLastPidAndReview() {
        val snapshot = DemoData.snapshot().copy(processes = (10..110).map { ProcessRow(it, "service-$it.exe", 1.0, 1048576) })
        ui.setContent { RdpTheme { CompositionLocalProvider(LocalDensity provides Density(1f, 1.5f)) {
            OnboardingScaffold { OnboardingBody { ProcessWorkspace(snapshot, {}, {}) } }
        } } }
        ui.onNodeWithTag("process-list").performScrollTo()
        ui.onNodeWithTag("process-list").performScrollToNode(hasTestTag("process-110"))
        ui.onNodeWithTag("process-110").assertIsDisplayed()
        ui.onNodeWithTag("select-process-110").performClick()
        ui.onNodeWithText("Review end action").performScrollTo().assertIsEnabled()
        capture("320-processes-large-text-last-row")
    }
}
