package io.github.mans230.rdpmonitor.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontVariation
import io.github.mans230.rdpmonitor.R
import androidx.compose.ui.unit.sp

val Ground: Color @Composable get() = MaterialTheme.colorScheme.background
val Panel: Color @Composable get() = MaterialTheme.colorScheme.surface
val Rule: Color @Composable get() = MaterialTheme.colorScheme.outline
val Muted: Color @Composable get() = MaterialTheme.colorScheme.onSurfaceVariant
val Signal: Color @Composable get() = MaterialTheme.colorScheme.onSurface
val Warning: Color @Composable get() = Signal
val Tray: Color @Composable get() = MaterialTheme.colorScheme.surfaceContainer
val LocalDarkAppearance = staticCompositionLocalOf { true }
val LocalToggleAppearance = staticCompositionLocalOf<() -> Unit> { {} }
@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
val InterfaceFont = FontFamily(
    Font(R.font.inter, FontWeight.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(400))),
    Font(R.font.inter, FontWeight.Medium, variationSettings = FontVariation.Settings(FontVariation.weight(500))),
    Font(R.font.inter, FontWeight.SemiBold, variationSettings = FontVariation.Settings(FontVariation.weight(600))),
    Font(R.font.inter, FontWeight.Bold, variationSettings = FontVariation.Settings(FontVariation.weight(700))))
val ReadingStyle = TextStyle(fontFamily = InterfaceFont, fontFeatureSettings = "tnum")

@Composable fun RdpTheme(content: @Composable () -> Unit) {
    val preferences = LocalContext.current.getSharedPreferences("appearance", android.content.Context.MODE_PRIVATE)
    var dark by remember { mutableStateOf(preferences.getBoolean("dark", true)) }
    val ground = if (dark) Color(0xFF161616) else Color.White
    val ink = if (dark) Color(0xFFF5F5F5) else Color(0xFF262626)
    val muted = if (dark) Color(0xFFA3A3A3) else Color(0xFF666666)
    val tray = if (dark) Color(0xFF202020) else Color(0xFFF5F5F5)
    val rule = if (dark) Color(0xFF333333) else Color(0xFFE6E6E6)
    val raised = if (dark) Color(0xFF303030) else Color(0xFFECECEC)
    val scheme = (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = ink, onPrimary = ground, background = ground, onBackground = ink,
        surface = ground, onSurface = ink, onSurfaceVariant = muted, surfaceVariant = tray,
        secondary = ink, onSecondary = ground, tertiary = ink, onTertiary = ground,
        primaryContainer = raised, onPrimaryContainer = ink, secondaryContainer = raised, onSecondaryContainer = ink,
        tertiaryContainer = raised, onTertiaryContainer = ink, outline = rule, outlineVariant = rule,
        surfaceTint = Color.Transparent, surfaceDim = ground, surfaceBright = raised,
        surfaceContainerLowest = ground, surfaceContainerLow = tray, surfaceContainer = tray,
        surfaceContainerHigh = tray, surfaceContainerHighest = raised,
        inverseSurface = ink, inverseOnSurface = ground, inversePrimary = ground,
        error = ink, onError = ground, errorContainer = tray, onErrorContainer = ink)
    val view = LocalView.current
    SideEffect {
        (view.context as? android.app.Activity)?.window?.let { window ->
            androidx.core.view.WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !dark; isAppearanceLightNavigationBars = !dark
            }
        }
    }
    MaterialTheme(colorScheme = scheme,
        shapes = Shapes(extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(6.dp),
            medium = RoundedCornerShape(10.dp), large = RoundedCornerShape(12.dp), extraLarge = RoundedCornerShape(8.dp)),
        typography = Typography(titleLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 24.sp, fontWeight = FontWeight.Medium),
            titleMedium = TextStyle(fontFamily = InterfaceFont, fontSize = 16.sp, fontWeight = FontWeight.Medium),
            bodyLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 14.sp, lineHeight = 21.sp), bodyMedium = TextStyle(fontFamily = InterfaceFont, fontSize = 13.sp, lineHeight = 19.sp),
            bodySmall = TextStyle(fontFamily = InterfaceFont, fontSize = 12.sp, lineHeight = 17.sp),
            labelLarge = TextStyle(fontFamily = InterfaceFont, fontSize = 13.sp, fontWeight = FontWeight.Medium)),
        content = { CompositionLocalProvider(LocalContentColor provides ink, LocalDarkAppearance provides dark,
            LocalToggleAppearance provides { dark = !dark; preferences.edit().putBoolean("dark", dark).apply() }) { content() } })
}
