package io.github.mans230.rdpmonitor.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Ground = Color(0xFF101113)
val Panel = Color(0xFF191B1F)
val Rule = Color(0xFF303238)
val Muted = Color(0xFFB1B6BF)
val Signal = Color(0xFF91CEFA)
val Warning = Color(0xFFF0C782)
val ReadingStyle = TextStyle(fontFamily = FontFamily.Monospace, fontFeatureSettings = "tnum")

@Composable fun RdpTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Signal, onPrimary = Ground, background = Ground,
        onBackground = Color(0xFFF2F3F5), surface = Panel, onSurface = Color(0xFFF2F3F5),
        surfaceVariant = Color(0xFF23262B), onSurfaceVariant = Muted, outline = Rule,
        error = Color(0xFFFFB4AB)),
        typography = Typography(titleLarge = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.SemiBold),
            titleMedium = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.Medium),
            bodyLarge = TextStyle(fontSize = 16.sp), bodyMedium = TextStyle(fontSize = 14.sp),
            labelLarge = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium)), content = content)
}
