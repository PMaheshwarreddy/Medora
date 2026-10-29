import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';

enum OrbState { idle, listening, thinking, speaking }

/// Dr. Medora's presence on screen. Drawn locally so it never competes with
/// the audio stream for bandwidth or CPU.
class MedoraOrb extends StatefulWidget {
  const MedoraOrb({super.key, this.state = OrbState.idle, this.size = 200});

  final OrbState state;
  final double size;

  @override
  State<MedoraOrb> createState() => _MedoraOrbState();
}

class _MedoraOrbState extends State<MedoraOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _period,
  )..repeat();

  Duration get _period => switch (widget.state) {
    OrbState.idle => const Duration(milliseconds: 3600),
    OrbState.listening => const Duration(milliseconds: 1800),
    OrbState.thinking => const Duration(milliseconds: 1200),
    OrbState.speaking => const Duration(milliseconds: 900),
  };

  /// The ring's colour says what Medora is doing: sage while she listens,
  /// terracotta while she speaks or thinks, pine at rest.
  Color get _ring => switch (widget.state) {
    OrbState.listening => MedoraColors.teal,
    OrbState.speaking || OrbState.thinking => MedoraColors.accent,
    OrbState.idle => MedoraColors.primary,
  };

  @override
  void didUpdateWidget(MedoraOrb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) {
      _controller
        ..duration = _period
        ..repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final amplitude = widget.state == OrbState.idle ? 0.025 : 0.06;
    final size = widget.size;
    return SizedBox.square(
      dimension: size,
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          final t = _controller.value * 2 * math.pi;
          return Stack(
            alignment: Alignment.center,
            children: [
              // Two fine rings breathing out of step: calm, not glowing.
              _outline(
                0.96 + amplitude * math.sin(t),
                _ring.withValues(alpha: 0.35),
                1.5,
              ),
              _outline(
                0.82 + amplitude * math.sin(t + 1.4),
                _ring.withValues(alpha: 0.7),
                2,
              ),
              Container(
                width: size * 0.62,
                height: size * 0.62,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  color: MedoraColors.primary,
                ),
                alignment: Alignment.center,
                child: Text(
                  'M',
                  style: TextStyle(
                    fontFamily: MedoraFonts.serif,
                    fontWeight: FontWeight.w600,
                    fontSize: size * 0.30,
                    height: 1,
                    color: const Color(0xFFF4EFE6),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _outline(double scale, Color color, double width) => Transform.scale(
    scale: scale,
    child: Container(
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: color, width: width),
      ),
    ),
  );
}
