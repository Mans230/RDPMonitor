package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.mans230.rdpmonitor.ui.theme.*

val LocalOnboardingBack = staticCompositionLocalOf<() -> Unit> { {} }
val LocalAppAccount = staticCompositionLocalOf<(() -> Unit)?> { null }
val LocalServerWorkspace = staticCompositionLocalOf<(() -> Unit)?> { null }

/** Native insets replace the reference's fixed artboard height; its content geometry is preserved. */
@Composable fun OnboardingScaffold(onBack: (() -> Unit)? = null, actions: @Composable RowScope.() -> Unit = {},
                                  footer: (@Composable () -> Unit)? = null, content: @Composable BoxScope.() -> Unit) {
    BoxWithConstraints(Modifier.fillMaxSize().then(pageMotion(onBack != null)).background(Ground).safeDrawingPadding().imePadding(), contentAlignment = Alignment.TopCenter) {
        val narrow = maxWidth < 350.dp
        Column(Modifier.widthIn(max = 410.dp).fillMaxSize().padding(horizontal = if (narrow) 20.dp else 24.dp, vertical = 24.dp)) {
            Row(Modifier.fillMaxWidth().heightIn(min = 36.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                Icon(CossIcons.Server, null, Modifier.size(21.dp))
                Text("RDPMonitor", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium.copy(fontSize = if (narrow) 14.sp else 15.sp, letterSpacing = (-.4).sp))
                actions()
                if (io.github.mans230.rdpmonitor.BuildConfig.DEBUG) MotionIconButton(onClick = LocalMotionPreview.current, modifier = Modifier.size(44.dp)) {
                    Icon(Icons.Outlined.PlayCircleOutline, "Motion previews", Modifier.size(18.dp))
                }
                val toggle = LocalToggleAppearance.current; val dark = LocalDarkAppearance.current
                MotionIconButton(onClick = toggle, modifier = Modifier.size(44.dp).offset(x = 7.dp)) {
                    Icon(if (dark) Icons.Outlined.LightMode else Icons.Outlined.DarkMode, "Toggle appearance", Modifier.size(18.dp))
                }
            }
            if (onBack != null) {
                Spacer(Modifier.height(30.dp))
                MotionIconButton(onClick = onBack, modifier = Modifier.size(44.dp).offset(x = (-8).dp)) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Go back", Modifier.size(18.dp))
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth(), content = content)
            footer?.let { Box(Modifier.fillMaxWidth().padding(top = 26.dp)) { it() } }
        }
    }
}

@Composable fun OnboardingBody(bottomInset: Int = 0, centered: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val bodyHeight = maxHeight
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min = bodyHeight).padding(bottom = bottomInset.dp),
            verticalArrangement = if (centered) Arrangement.Center else Arrangement.Top, content = content)
    }
}

@Composable fun OnboardingHeadline(text: String, server: Boolean = false) {
    BoxWithConstraints {
        Text(text, Modifier.testTag(if (server) "add-server-heading" else "onboarding-heading"),
            style = MaterialTheme.typography.titleLarge.copy(fontSize = if (server) { if (maxWidth < 310.dp) 26.sp else 28.sp } else { if (maxWidth < 310.dp) 29.sp else 31.sp },
                lineHeight = if (server) 34.sp else 37.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-1.1).sp))
    }
}

@Composable fun OnboardingMark(small: Boolean = false) {
    Surface(Modifier.size(if (small) 54.dp else 66.dp), shape = RoundedCornerShape(if (small) 14.dp else 18.dp),
        color = Tray, border = BorderStroke(1.dp, Rule)) {
        Box(contentAlignment = Alignment.Center) { Icon(CossIcons.ServerThin, null, Modifier.size(if (small) 27.dp else 32.dp)) }
    }
}

@Composable fun WelcomePage(onStart: () -> Unit) {
    val narrow = LocalConfiguration.current.screenWidthDp < 350
    OnboardingScaffold(footer = { OnboardingPrimary("Get started", onStart) }) {
        OnboardingBody(bottomInset = 26, centered = true) {
            BoxWithConstraints(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                EngineArtwork(Modifier.widthIn(max = 320.dp).fillMaxWidth().height(if (maxWidth < 310.dp) 215.dp else 240.dp))
            }
            Spacer(Modifier.height(if (narrow) 28.dp else 35.dp))
            Box(Modifier.padding(start = 4.dp)) { OnboardingHeadline("Your servers.\nOne place.") }
        }
    }
}

@Composable fun GoogleSignInPage(onBack: () -> Unit, onSignIn: () -> Unit, enabled: Boolean, error: String?) {
    OnboardingScaffold(onBack, footer = {
        Box(Modifier.fillMaxWidth().height(24.dp).padding(bottom = 8.dp), contentAlignment = Alignment.Center) {
            Icon(Icons.Outlined.VerifiedUser, null, Modifier.size(16.dp), tint = Muted)
        }
    }) {
        OnboardingBody(bottomInset = 65, centered = true) {
            Column(Modifier.padding(horizontal = 4.dp)) {
                OnboardingMark(); Spacer(Modifier.height(28.dp))
                OnboardingHeadline("Sign in to\nRDPMonitor.")
                Spacer(Modifier.height(42.dp))
                CossOutlinedButton(onClick = onSignIn, enabled = enabled, modifier = Modifier.fillMaxWidth().height(48.dp)) {
                    Image(GoogleMark, null, Modifier.size(20.dp)); Spacer(Modifier.width(12.dp)); Text("Continue with Google")
                }
                error?.let { Spacer(Modifier.height(18.dp)); Text(it, color = Signal, style = MaterialTheme.typography.bodyMedium) }
            }
        }
    }
}

@Composable fun OnboardingPrimary(label: String, action: () -> Unit, enabled: Boolean = true) {
    val phone = LocalConfiguration.current.screenWidthDp < 640
    CossButton(onClick = action, enabled = enabled, modifier = Modifier.fillMaxWidth().heightIn(min = if (phone) 44.dp else 40.dp)) {
        Text(label, Modifier.weight(1f)); Icon(CossIcons.ArrowRight, null, Modifier.size(18.dp))
    }
}
