package io.github.mans230.rdpmonitor

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import io.github.mans230.rdpmonitor.data.DemoDocuments
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import kotlinx.serialization.json.*
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
class ContextualControlsTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    @Test fun structuredCloudQuestionPreservesItsIdAndReviewableDefault() {
        val data = Json.parseToJsonElement("""{"jobs":[{"id":"fixture-job","op":"authorize","state":"running","message":"Choose a drive","question":{"id":"fixture-question","name":"Choose drive","secret":false,"required":true,"default":"drive-one","choices":[{"value":"drive-one","label":"Personal drive"}]}}]}""")
        var selected: Tool? = null; var values: Map<String, String> = emptyMap()
        ui.setContent { RdpTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            ContextualDocument(Feature.Cloud, "/api/setup/jobs", data, {}, { tool, initial -> selected = tool; values = initial })
        } } }
        ui.onNodeWithText("Answer sign-in question").performScrollTo().performClick()
        ui.runOnIdle {
            val body = selected!!.payload(values)
            assertEquals("fixture-job", body["job"]!!.jsonPrimitive.content)
            assertEquals("fixture-question", body["question"]!!.jsonPrimitive.content)
            assertEquals("drive-one", body["value"]!!.jsonPrimitive.content)
            assertTrue(selected!!.safeArguments(body).toString().contains("drive-one"))
        }
    }
    @Test fun contextualAppSessionRetainsTheExistingRevokeControl() {
        var selected: Tool? = null
        ui.setContent { RdpTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            ContextualDocument(Feature.Access, "/api/mobile/v1/sessions", DemoDocuments.at("/api/mobile/v1/sessions"), {}, { tool, _ -> selected = tool })
        } } }
        ui.onNodeWithText("Revoke app session").performScrollTo().performClick()
        ui.runOnIdle { assertEquals("mobile_revoke", selected!!.action); assertEquals("sample-session", selected!!.fixed["id"]) }
    }
}
