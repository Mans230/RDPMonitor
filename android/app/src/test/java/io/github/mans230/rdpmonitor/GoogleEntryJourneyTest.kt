package io.github.mans230.rdpmonitor

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.lifecycle.ViewModelProvider
import io.github.mans230.rdpmonitor.core.security.GoogleProfile
import io.github.mans230.rdpmonitor.ui.AppEntry
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Simulates only the credential-provider boundary. No real Google authentication is claimed. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class GoogleEntryJourneyTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    private fun start(result: CompletableDeferred<GoogleProfile>): RdpViewModel {
        val model = ViewModelProvider(ui.activity)[RdpViewModel::class.java]
        ui.setContent { RdpTheme { AppEntry(model, {}, signIn = { _, clientId ->
            check(clientId == BuildConfig.GOOGLE_WEB_CLIENT_ID)
            result.await()
        }) } }
        return model
    }
    @Test fun googleProviderSuccessOpensConnectorsWithoutGrantingServerAccess() {
        val result = CompletableDeferred<GoogleProfile>()
        val model = start(result)
        ui.onNodeWithText("Continue with Google").performScrollTo().performClick()
        ui.onNodeWithText("Signing in with Google").assertIsDisplayed()
        ui.runOnIdle { result.complete(GoogleProfile("fixture-google-subject", "fixture@example.test", "Sample account")) }
        ui.onNodeWithText("Your RDP connectors").assertIsDisplayed()
        ui.onNodeWithText("Sample account").assertExists()
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
        ui.onNodeWithText("Continue with Google").performScrollTo().performClick()
        ui.onNodeWithText("Signing in with Google").assertIsDisplayed()
        ui.runOnIdle { result.completeExceptionally(GetCredentialCancellationException()) }
        ui.onNodeWithText("Sign-in cancelled. You can try again.").assertExists()
        ui.onNodeWithText("Continue with Google").assertIsEnabled()
        ui.runOnIdle {
            val preferences = ui.activity.getSharedPreferences("app_identity", Context.MODE_PRIVATE)
            assertNull(preferences.getString("subject", null))
            assertNull(preferences.getString("connector_owner", null))
        }
    }
}
