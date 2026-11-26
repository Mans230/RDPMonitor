package io.github.mans230.rdpmonitor.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontVariation
import io.github.mans230.rdpmonitor.R
import androidx.compose.ui.unit.sp

val Ground = Color(0xFF080808)
val Panel = Color(0xFF161616)
val Rule = Color(0xFF343434)
val Muted = Color(0xFFB5B5B5)
val Signal = Color(0xFFF5F5F5)
// Status always has a written label; the selected direction uses no hue.
val Warning = Color(0xFFF5F5F5)
@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
val InterfaceFont = FontFamily(
    Font(R.font.inter, FontWeight.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(400))),
    Font(R.font.inter, FontWeight.Medium, variationSettings = FontVariation.Settings(FontVariation.weight(500))),
    Font(R.font.inter, FontWeight.SemiBold, variationSettings = FontVariation.Settings(FontVariation.weight(600))),
    Font(R.font.inter, FontWeight.Bold, variationSettings = FontVariation.Settings(FontVariation.weight(700))))
val ReadingStyle = TextStyle(fontFamily = InterfaceFont, fontFeatureSettings = "tnum")

@Composable fun RdpTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Signal, onPrimary = Ground, background = Ground,
        onBackground = Signal, surface = Panel, onSurface = Signal,
        secondary = Signal, tertiary = Signal, surfaceTint = Color.Transparent,
        surfaceVariant = Color(0xFF222222), onSurfaceVariant = Muted, outline = Rule,
        error = Signal, onError = Ground, errorContainer = Panel, onErrorContainer = Signal,
        onSecondary = Ground, onTertiary = Ground, primaryContainer = Rule, onPrimaryContainer = Signal,
        secondaryContainer = Rule, onSecondaryContainer = Signal, tertiaryContainer = Rule, onTertiaryContainer = Signal,
        surfaceDim = Ground, surfaceBright = Rule, surfaceContainerLowest = Ground, surfaceContainerLow = Panel,
        surfaceContainer = Panel, surfaceContainerHigh = Color(0xFF222222), surfaceContainerHighest = Rule,
        outlineVariant = Rule, inverseSurface = Signal, inverseOnSurface = Ground, inversePrimary = Ground),
        typography = Typography(titleLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 24.sp, fontWeight = FontWeight.Medium),
            titleMedium = TextStyle(fontFamily = InterfaceFont, fontSize = 16.sp, fontWeight = FontWeight.Medium),
            bodyLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 14.sp, lineHeight = 21.sp), bodyMedium = TextStyle(fontFamily = InterfaceFont, fontSize = 13.sp, lineHeight = 19.sp),
            bodySmall = TextStyle(fontFamily = InterfaceFont, fontSize = 12.sp, lineHeight = 17.sp),
            labelLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 13.sp, fontWeight = FontWeight.Medium)),
        content = { CompositionLocalProvider(LocalContentColor provides Signal) { content() } })
}
