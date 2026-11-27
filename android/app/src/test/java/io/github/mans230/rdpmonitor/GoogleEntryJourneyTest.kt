package io.github.mans230.rdpmonitor

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.lifecycle.ViewModelProvider
import io.github.mans230.rdpmonitor.core.security.GoogleProfile
import io.github.mans230.rdpmonitor.ui.AppEntry
import io.github.mans230.rdpmonitor.ui.components.AppearanceShell
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.compose.ui.semantics.SemanticsProperties
import io.github.mans230.rdpmonitor.core.storage.DeviceStore
import io.github.mans230.rdpmonitor.core.model.ServerProfile
import java.io.File

/** Simulates only the credential-provider boundary. No real Google authentication is claimed. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class GoogleEntryJourneyTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    private fun start(result: CompletableDeferred<GoogleProfile>): RdpViewModel {
        // Keep each Robolectric application's profile storage isolated from cached default factories.
        val model = ViewModelProvider(ui.activity, ViewModelProvider.AndroidViewModelFactory(ui.activity.application))[RdpViewModel::class.java]
        ui.setContent { RdpTheme { AppearanceShell { AppEntry(model, {}, signIn = { _, clientId ->
            check(clientId == BuildConfig.GOOGLE_WEB_CLIENT_ID)
            result.await()
        }) } } }
        return model
    }
    @Test fun googleProviderSuccessOpensConnectorsWithoutGrantingServerAccess() {
        val result = CompletableDeferred<GoogleProfile>()
        val model = start(result)
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("Continue with Google").performClick()
        ui.onNodeWithText("Signing in").assertIsDisplayed()
        ui.runOnIdle { result.complete(GoogleProfile("fixture-google-subject", "fixture@example.test", "Sample account")) }
        ui.onNodeWithText("Add your server.").assertIsDisplayed()
        ui.onNodeWithText("Server name").assertIsDisplayed()
        ui.runOnIdle {
            val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
            assertEquals("fixture-google-subject", preferences.getString("connector_owner", null))
            assertFalse(model.state.value.connected)
            assertFalse(model.state.value.administration)
            assertNull(model.state.value.snapshot)
            assertNull(model.state.value.review)
        }
    }
    @Test fun cancellationReturnsToWelcomeWithRetryAndDoesNotCacheAnIdentity() {
        val result = CompletableDeferred<GoogleProfile>()
        start(result)
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("Continue with Google").performClick()
        ui.onNodeWithText("Signing in").assertIsDisplayed()
        ui.runOnIdle { result.completeExceptionally(GetCredentialCancellationException()) }
        ui.onNodeWithText("Sign-in cancelled. Try again.").assertExists()
        ui.onNodeWithText("Continue with Google").assertIsEnabled()
        ui.runOnIdle {
            val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
            assertNull(preferences.getString("subject", null))
            assertNull(preferences.getString("connector_owner", null))
        }
    }

    @Test fun backDuringSignInCannotCacheALateProviderResult() {
        val result = CompletableDeferred<GoogleProfile>()
        start(result)
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("Continue with Google").performClick()
        ui.runOnIdle { ui.activity.onBackPressedDispatcher.onBackPressed() }
        ui.onNodeWithText("Continue with Google").assertIsEnabled()
        ui.runOnIdle { result.complete(GoogleProfile("late-subject", "late@example.test", "Late")) }
        ui.onNodeWithText("Add your server.").assertDoesNotExist()
        ui.runOnIdle { assertNull(ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE).getString("subject", null)) }
    }

    @Test fun returningAccountStartsAtWelcomeAndBackCannotRepeatGoogleLogin() {
        val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
        preferences.edit().putString("connector_owner", "returning-subject").putString("subject", "returning-subject").putString("name", "Returning").commit()
        DeviceStore(ui.activity).save(ServerProfile(id = "saved", name = "Work server", origin = "https://work.tailnet.ts.net"))
        val result = CompletableDeferred<GoogleProfile>()
        val model = start(result)
        ui.runOnIdle { assertEquals("Stored profiles", listOf("saved"), DeviceStore(ui.activity).profiles().map { it.id }); assertEquals("Loaded profiles", listOf("saved"), model.state.value.profiles.map { it.id }) }
        ui.onNodeWithText("Get started").assertIsDisplayed().performClick()
        ui.onNodeWithText("Server connections").assertIsDisplayed()
        ui.onNodeWithText("Work server").assertIsDisplayed()
        ui.onNodeWithTag("server-saved").performClick()
        ui.onNodeWithText("Reconnect").assertIsDisplayed()
        ui.onNodeWithText("Done").performClick()
        ui.onNodeWithText("Continue with Google").assertDoesNotExist()
        ui.onNodeWithText("Add server").performClick()
        ui.onNodeWithContentDescription("Server name").assertTextContains("")
        ui.onNodeWithContentDescription("Go back").performClick()
        ui.onNodeWithText("Server connections").assertIsDisplayed()
        ui.onNodeWithContentDescription("Go back").performClick()
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("Server connections").assertIsDisplayed()
        ui.onNodeWithText("Continue with Google").assertDoesNotExist()
        ui.runOnIdle { assertEquals(listOf("saved"), model.state.value.profiles.map { it.id }); assertFalse(model.state.value.connected) }
        ui.onNodeWithTag("section-navigation").assertIsDisplayed()
        ui.onNode(hasText("Overview") and hasClickAction()).performClick()
        ui.onNodeWithText("Server disconnected").assertIsDisplayed()
        ui.onNodeWithTag("section-navigation").assertIsDisplayed()
        ui.onNode(hasText("More") and hasClickAction()).performClick()
        ui.onNodeWithText("All sections").assertIsDisplayed()
        ui.onNodeWithText("Server disconnected").assertDoesNotExist()
        ui.onNodeWithContentDescription("Server connections").performClick()
        ui.onNodeWithText("Work server").assertIsDisplayed()
        ui.onNodeWithText("Continue with Google").assertDoesNotExist()
    }

    @Test fun signOutThenDifferentGoogleAccountShowsOnlyItsOwnServers() {
        val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
        preferences.edit().putString("connector_owner", "account-b").commit()
        DeviceStore(ui.activity).save(ServerProfile(id = "b", name = "B server", origin = "https://b.tailnet.ts.net"))
        preferences.edit().putString("connector_owner", "account-a").putString("subject", "account-a").commit()
        DeviceStore(ui.activity).save(ServerProfile(id = "a", name = "A server", origin = "https://a.tailnet.ts.net"))
        val result = CompletableDeferred<GoogleProfile>()
        start(result)
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("A server").assertIsDisplayed()
        ui.onNodeWithText("B server").assertDoesNotExist()
        ui.onNodeWithContentDescription("Account").performClick()
        ui.onNodeWithText("Sign out").performScrollTo().performClick()
        ui.onNodeWithTag("confirm-account-signout").performClick()
        ui.onNodeWithText("Get started").assertIsDisplayed().performClick()
        ui.onNodeWithText("Continue with Google").performClick()
        ui.runOnIdle { result.complete(GoogleProfile("account-b", "b@example.test", "B")) }
        ui.onNodeWithText("Server connections").assertIsDisplayed()
        ui.onNodeWithText("B server").assertIsDisplayed()
        ui.onNodeWithText("A server").assertDoesNotExist()
    }

    @Test fun mismatchedCachedIdentityRequiresGoogleWithoutExposingOrReassigningProfiles() {
        val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
        preferences.edit().putString("connector_owner", "owner-a").putString("subject", "different-owner").commit()
        DeviceStore(ui.activity).save(ServerProfile(id = "private-a", name = "Owner A server", origin = "https://a.tailnet.ts.net"))
        val model = start(CompletableDeferred())
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithText("Continue with Google").assertIsDisplayed()
        ui.onNodeWithText("Owner A server").assertDoesNotExist()
        ui.runOnIdle {
            assertEquals("owner-a", preferences.getString("connector_owner", null))
            assertEquals("private-a", DeviceStore(ui.activity).profiles().single().id)
            model.connect("Work", "https://work.tailnet.ts.net")
            assertFalse(model.state.value.busy)
            assertNull(model.state.value.selected)
            assertNull(DeviceStore(ui.activity).accountOwner())
        }
    }

    @Test fun savedServerRemovalRequiresConfirmationAndCancelPreservesIt() {
        val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
        preferences.edit().putString("connector_owner", "owner-a").putString("subject", "owner-a").commit()
        DeviceStore(ui.activity).save(ServerProfile(id = "owned", name = "Work", origin = "https://work.tailnet.ts.net"))
        val model = start(CompletableDeferred())
        ui.onNodeWithText("Get started").performClick()
        ui.onNodeWithTag("server-owned").performClick()
        ui.onNodeWithText("Remove saved server").performClick()
        ui.runOnIdle { assertEquals(1, DeviceStore(ui.activity).profiles().size) }
        ui.onNodeWithText("Cancel").performClick()
        ui.onNodeWithTag("server-owned").assertIsDisplayed().performClick()
        ui.onNodeWithText("Remove saved server").performClick()
        ui.onNodeWithText("Remove server").performClick()
        ui.onNodeWithText("No servers added yet.").assertIsDisplayed()
        ui.runOnIdle { assertTrue(DeviceStore(ui.activity).profiles().isEmpty()); assertTrue(model.state.value.profiles.isEmpty()); assertEquals("owner-a", preferences.getString("subject", null)) }
    }

    private fun capture(name: String) {
        ui.waitForIdle()
        lateinit var bitmap: Bitmap
        ui.runOnIdle { val view = ui.activity.window.decorView; bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap)) }
        File("build/reports/app-journeys/$name.png").apply { parentFile!!.mkdirs() }.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }
    private fun onboardingAt(width: Int) {
        val result = CompletableDeferred<GoogleProfile>()
        val model = start(result)
        listOf("dark", "light").forEachIndexed { index, theme ->
            if (index == 1) ui.onNodeWithContentDescription("Toggle appearance").performClick()
            capture("$width-onboarding-welcome-$theme")
            ui.onNodeWithText("Get started").assertIsDisplayed().performClick()
            if (index == 1) {
                ui.onNodeWithText("Server connections").assertIsDisplayed()
                ui.onNodeWithText("Continue with Google").assertDoesNotExist()
                capture("$width-account-servers-$theme")
                ui.onNodeWithText("Add server").performClick()
            } else {
            capture("$width-onboarding-google-$theme")
            ui.onNodeWithText("Continue with Google").assertIsDisplayed().performClick()
            if (index == 0) ui.runOnIdle { result.complete(GoogleProfile("screenshot-subject", "fixture@example.test", "Fixture")) }
            }
            ui.onNodeWithText("Add your server.").assertIsDisplayed()
            capture("$width-onboarding-server-$theme")
            val input = ui.onNodeWithContentDescription("Server name").fetchSemanticsNode().config[SemanticsProperties.EditableText].text
            assertEquals("", input)
            ui.onNodeWithText("Connect server").assertIsDisplayed()
            ui.onNodeWithText("Explore offline demo").assertDoesNotExist()
            ui.onNodeWithText("Use a private workspace without Google").assertDoesNotExist()
            ui.onNodeWithContentDescription("Go back").performClick()
            ui.onNodeWithText("Server connections").assertIsDisplayed()
            capture("$width-account-servers-$theme")
            ui.onNodeWithContentDescription("Account").performClick()
            capture("$width-account-$theme")
            ui.onNodeWithContentDescription("Go back").performClick()
            ui.onNodeWithContentDescription("Go back").performClick()
            ui.runOnIdle { assertFalse(model.state.value.connected); assertNull(model.state.value.review) }
        }
    }
    @Test fun onboardingAt390InBothThemes() = onboardingAt(390)
    @Test @Config(qualifiers = "w320dp-h740dp-mdpi") fun onboardingAt320InBothThemes() = onboardingAt(320)
    @Test @Config(qualifiers = "w768dp-h1024dp-mdpi") fun onboardingAt768InBothThemes() = onboardingAt(768)
}
