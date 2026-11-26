package io.github.mans230.rdpmonitor

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import io.github.mans230.rdpmonitor.feature.more.Feature
import io.github.mans230.rdpmonitor.core.storage.DeviceStore
import io.github.mans230.rdpmonitor.core.model.ServerProfile
import android.content.Context
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowDialog
import java.io.File

/** Real Compose screens and callbacks, isolated app storage, no server credentials/network actions. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AppJourneyTest {
    @get:Rule val ui = createAndroidComposeRule<MainActivity>()
    private val model get() = ViewModelProvider(ui.activity)[RdpViewModel::class.java]

    private fun preview() { ui.runOnIdle { model.preview() }; ui.waitForIdle() }
    private fun workspace(text: String) {
        ui.onNodeWithTag("app-content").performScrollToNode(hasText(text))
        ui.onNodeWithText(text).assertIsDisplayed()
        alignWorkspace(ui.onNodeWithText(text))
    }
    private fun alignWorkspace(node: SemanticsNodeInteraction) {
        val delta = node.fetchSemanticsNode().boundsInRoot.top - ui.onNodeWithTag("app-content").fetchSemanticsNode().boundsInRoot.top
        if (delta > 0) ui.onNodeWithTag("app-content").performSemanticsAction(SemanticsActions.ScrollBy) { it(0f, delta) }
        ui.waitForIdle()
    }
    private fun dock(label: String) {
        ui.onNodeWithTag("app-content").performScrollToNode(hasText(label) and hasClickAction())
        ui.onNode(hasText(label) and hasClickAction()).performClick()
    }
    private fun screenshot(name: String) {
        ui.waitForIdle()
        // Draw the real decor view: PixelCopy captureToImage does not complete on Windows RNG.
        lateinit var bitmap: Bitmap
        ui.runOnIdle {
            val dialog = ShadowDialog.getLatestDialog()
            val view = if (dialog?.isShowing == true) dialog.window!!.decorView else ui.activity.window.decorView
            check(view.width > 0 && view.height > 0)
            bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
        }
        val output = File("build/reports/app-journeys/$name.png").apply { parentFile!!.mkdirs() }
        output.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun serverChooserReturnsToMonitorInsteadOfForcingLogin() {
        ui.onNodeWithText("Explore offline demo").performScrollTo().performClick()
        ui.onNodeWithContentDescription("Server connections").performClick()
        ui.onNodeWithText("Back to demo").assertIsDisplayed().performClick()
        ui.onNodeWithText("Server overview").assertExists()
        ui.runOnIdle { check(model.state.value.demo); check(!model.state.value.connectionScreen) }
        screenshot("390-overview")
    }
    @Test fun defaultHeadingsHaveVisibleInkOnTransparentDarkSurfaces() {
        preview()
        val bounds = ui.onNodeWithTag("page-title-Server overview").fetchSemanticsNode().boundsInRoot
        lateinit var bitmap: Bitmap
        ui.runOnIdle { val view = ui.activity.window.decorView; bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap)) }
        var readable = 0
        for (y in bounds.top.toInt().coerceAtLeast(0) until bounds.bottom.toInt().coerceAtMost(bitmap.height)) {
            for (x in bounds.left.toInt().coerceAtLeast(0) until bounds.right.toInt().coerceAtMost(bitmap.width)) {
                val pixel = bitmap.getPixel(x, y)
                if (Color.red(pixel) > 150 && Color.green(pixel) > 150 && Color.blue(pixel) > 150) readable++
            }
        }
        check(readable > 15) { "Dark default text became invisible on the transparent app surface." }
    }
    @Test fun welcomeExplainsGoogleAndPrivateConnectorsBeforeNavigation() {
        ui.onNodeWithText("Continue with Google").assertExists()
        screenshot("390-welcome")
        ui.onNodeWithText("Use a private workspace without Google").performScrollTo().performClick()
        ui.onNodeWithText("Your RDP connectors").assertIsDisplayed()
        screenshot("390-connectors")
        ui.runOnIdle { check(!model.state.value.connected); check(model.state.value.review == null) }
    }
    @Test fun connectorsAreIsolatedBetweenGoogleAccountsAndLegacyPrivateWorkspace() {
        val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
        val store = DeviceStore(ui.activity)
        ui.runOnIdle {
            preferences.edit().clear().commit()
            store.save(ServerProfile(id = "legacy", name = "Private connector", origin = "https://private.tail.ts.net"))
            preferences.edit().putString("connector_owner", "google-subject-one").commit()
            check(store.profiles().isEmpty())
            store.save(ServerProfile(id = "first", name = "Account one", origin = "https://one.tail.ts.net"))
            preferences.edit().putString("connector_owner", "google-subject-two").commit()
            check(store.profiles().isEmpty())
            preferences.edit().putString("connector_owner", "google-subject-one").commit()
            check(store.profiles().single().id == "first")
            preferences.edit().clear().commit()
            check(store.profiles().single().id == "legacy")
        }
    }

    @Test fun everySectionOpensAndReturnsWithoutLosingTheServer() {
        preview()
        Feature.entries.forEach { feature ->
            dock("More")
            ui.onNodeWithTag("app-content").performScrollToNode(hasTestTag("feature-${feature.name}"))
            ui.onNodeWithTag("feature-${feature.name}").performClick()
            ui.onNodeWithTag("app-content").performScrollToNode(hasTestTag("page-title-${feature.title}"))
            ui.onNodeWithTag("page-title-${feature.title}").assertIsDisplayed()
            alignWorkspace(ui.onNodeWithTag("page-title-${feature.title}"))
            screenshot("390-section-${feature.name}")
            ui.runOnIdle { check(model.state.value.snapshot != null); check(!model.state.value.connectionScreen) }
            ui.runOnIdle { ui.activity.onBackPressedDispatcher.onBackPressed() }
            workspace("All sections")
        }
    }

    @Test fun demoCannotRunDiagnosticsOrServerActions() {
        preview(); dock("More"); workspace("Diagnostics"); ui.onNodeWithText("Diagnostics").performClick()
        workspace("Run diagnostic")
        ui.onNodeWithText("Run diagnostic").assertIsNotEnabled()
        screenshot("390-diagnostics-demo")
        dock("Backups"); workspace("Back up now")
        ui.onNodeWithText("Back up now").assertIsNotEnabled()
        ui.runOnIdle { check(!model.state.value.actionBusy); check(model.state.value.review == null) }
    }
    @Test fun backupNumbersStayWithTheirRunArchiveAndRetentionLabels() {
        preview(); dock("Backups"); workspace("Latest backup result")
        ui.onNodeWithText("Files processed in the latest run").assertIsDisplayed()
        ui.onNodeWithText("42").assertIsDisplayed()
        ui.onNodeWithText("No job running").assertExists()
        workspace("Stored archives")
        ui.onNodeWithText("Archive size").assertIsDisplayed()
        ui.onNodeWithText("500 MiB").assertIsDisplayed()
        ui.onNodeWithText("Archive last modified").assertExists()
        ui.onNodeWithText("Worker").assertDoesNotExist()
        screenshot("390-backup-archives")
        workspace("Local retention")
        ui.onNodeWithText("Up to 3 local copies").assertIsDisplayed()
        screenshot("390-backup-plan")
        workspace("Back up now"); ui.onNodeWithText("Back up now").assertIsNotEnabled()
    }

    @Test @Config(qualifiers = "w320dp-h740dp-mdpi") fun narrowPhoneCanReachWorkspaceAndAppearance() {
        preview(); screenshot("320-overview")
        workspace("Remote sessions"); screenshot("320-workspace")
        dock("Overview")
        ui.onNodeWithTag("app-content").performScrollToIndex(0)
        ui.onNodeWithContentDescription("Appearance").performClick()
        ui.onNodeWithText("Choose background image").assertIsDisplayed()
        ui.onNodeWithText("Remove background").assertIsNotEnabled()
        screenshot("320-appearance")
        ui.onNodeWithText("Done").performClick()
        dock("Backups"); workspace("Latest backup result"); screenshot("320-backup-result")
        workspace("Stored archives"); screenshot("320-backup-archives")
    }

    @Test @Config(qualifiers = "w768dp-h1024dp-mdpi") fun tabletShowsResourcesAndWorkspace() {
        preview(); screenshot("768-overview")
        workspace("Remote sessions"); screenshot("768-workspace")
        dock("Backups"); workspace("Latest backup result"); screenshot("768-backup-result")
        workspace("Local retention"); screenshot("768-backup-plan")
    }
}
