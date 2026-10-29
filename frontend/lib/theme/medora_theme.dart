import 'package:flutter/material.dart';

/// Medora's palette: warm paper, deep pine green, and one terracotta accent
/// for what is live or needs attention. Deliberately not the blue-on-white
/// of every software product: it should feel like a well-run clinic.
abstract final class MedoraColors {
  static const background = Color(0xFFF4EFE6); // paper
  static const surface = Color(0xFFFFFCF7); // card
  static const field = Color(0xFFFAF6EF); // inputs, quiet panels
  static const border = Color(0xFFE4DACB); // warm hairline
  static const primary = Color(0xFF1D4D3B); // pine
  static const primaryDark = Color(0xFF12352A);
  static const accent = Color(0xFFC8573A); // terracotta
  static const teal = Color(0xFF3F8A68); // sage: normal, done
  static const violet = accent; // historical name for the secondary accent
  static const ochre = Color(0xFFB7821E);
  static const navy = Color(0xFF0F271E); // ink
  static const text = Color(0xFF1B231F);
  static const muted = Color(0xFF6E685E);
  static const warning = Color(0xFFA65A0C);
  static const danger = Color(0xFFB3261E);
}

/// Fraunces (a soft serif) for headings and figures, Public Sans for
/// everything that has to be read quickly.
abstract final class MedoraFonts {
  static const serif = 'Fraunces';
  static const sans = 'PublicSans';

  /// For letters the main fonts lack: Malayalam.
  static const malayalam = 'NotoSansMalayalam';
  static const fallback = [malayalam];
}

abstract final class MedoraTheme {
  static const cardShadow = [
    BoxShadow(color: Color(0x0D3B2A14), blurRadius: 18, offset: Offset(0, 6)),
  ];

  /// The brand fill: pine, with only a hint of depth.
  static const brandGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF235A45), Color(0xFF173F31)],
  );

  /// The dark surface behind the sidebar and the sign-in brand panel.
  static const nightGradient = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [Color(0xFF12352A), Color(0xFF0F271E)],
  );

  /// A barely-there two-tone fill from one hue, for badges and bars.
  static LinearGradient tint(Color color) => LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color.lerp(color, Colors.white, 0.08)!, color],
  );

  static ThemeData light() {
    final scheme =
        ColorScheme.fromSeed(
          seedColor: MedoraColors.primary,
          brightness: Brightness.light,
        ).copyWith(
          primary: MedoraColors.primary,
          secondary: MedoraColors.teal,
          surface: MedoraColors.surface,
          onSurface: MedoraColors.text,
          error: MedoraColors.danger,
          outline: MedoraColors.border,
        );

    final radius = BorderRadius.circular(12);
    OutlineInputBorder inputBorder(Color color, [double width = 1]) =>
        OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: color, width: width),
        );

    return ThemeData(
      useMaterial3: true,
      fontFamily: MedoraFonts.sans,
      // Malayalam letters come from Noto Sans Malayalam, bundled so they
      // show without internet; Fraunces and Public Sans have none.
      fontFamilyFallback: MedoraFonts.fallback,
      colorScheme: scheme,
      scaffoldBackgroundColor: MedoraColors.background,
      textTheme: const TextTheme(
        displaySmall: TextStyle(
          fontFamily: MedoraFonts.serif,
          fontSize: 44,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.8,
          color: MedoraColors.text,
          height: 1.15,
        ),
        headlineSmall: TextStyle(
          fontFamily: MedoraFonts.serif,
          fontSize: 28,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.3,
          color: MedoraColors.text,
        ),
        titleLarge: TextStyle(
          fontFamily: MedoraFonts.serif,
          fontSize: 21,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
          color: MedoraColors.text,
        ),
        titleMedium: TextStyle(
          fontSize: 17,
          fontWeight: FontWeight.w600,
          color: MedoraColors.text,
        ),
        bodyLarge: TextStyle(fontSize: 18, color: MedoraColors.text),
        bodyMedium: TextStyle(fontSize: 16, color: MedoraColors.muted),
        labelLarge: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
      ),
      // Kiosk touch targets: every button is at least 56px tall.
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 56),
          padding: const EdgeInsets.symmetric(horizontal: 28),
          shape: RoundedRectangleBorder(borderRadius: radius),
          textStyle: const TextStyle(
            fontFamily: MedoraFonts.sans,
            fontFamilyFallback: MedoraFonts.fallback,
            fontSize: 17,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 56),
          padding: const EdgeInsets.symmetric(horizontal: 28),
          side: const BorderSide(color: MedoraColors.border),
          shape: RoundedRectangleBorder(borderRadius: radius),
          textStyle: const TextStyle(
            fontFamily: MedoraFonts.sans,
            fontFamilyFallback: MedoraFonts.fallback,
            fontSize: 17,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      // An off switch must read as "off", not as "disabled".
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? Colors.white
              : const Color(0xFF8A8173),
        ),
        trackColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? MedoraColors.primary
              : const Color(0xFFEDE5D8),
        ),
        trackOutlineColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? Colors.transparent
              : const Color(0xFFA39A8B),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          textStyle: const TextStyle(
            fontFamily: MedoraFonts.sans,
            fontFamilyFallback: MedoraFonts.fallback,
            fontSize: 15,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: MedoraColors.field,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 18,
          vertical: 18,
        ),
        border: inputBorder(MedoraColors.border),
        enabledBorder: inputBorder(MedoraColors.border),
        focusedBorder: inputBorder(MedoraColors.primary, 2),
        errorBorder: inputBorder(MedoraColors.warning, 1.5),
        focusedErrorBorder: inputBorder(MedoraColors.warning, 2),
        errorStyle: const TextStyle(color: MedoraColors.warning, fontSize: 14),
        labelStyle: const TextStyle(color: MedoraColors.muted),
      ),
    );
  }
}
