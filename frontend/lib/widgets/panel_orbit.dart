import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/intake.dart';
import '../theme/medora_theme.dart';

/// An icon for each specialty on the panel roster (`backend/app/panel.py`).
const specialistIcons = <String, IconData>{
  'Pediatrics': Icons.child_care_rounded,
  'Cardiology': Icons.favorite_rounded,
  'Dermatology': Icons.back_hand_rounded,
  'Gastroenterology': Icons.restaurant_rounded,
  'Neurology': Icons.psychology_rounded,
  'Pulmonology': Icons.air_rounded,
  'Nephrology': Icons.water_drop_rounded,
  'Endocrinology': Icons.bloodtype_rounded,
  'Oncology': Icons.biotech_rounded,
  'General Surgery': Icons.content_cut_rounded,
  'Orthopedic Surgery': Icons.accessibility_new_rounded,
  'Neurosurgery': Icons.hub_rounded,
  'Ophthalmology': Icons.visibility_rounded,
  'Urology': Icons.wc_rounded,
  'Otolaryngology (ENT)': Icons.hearing_rounded,
  'Obstetrics & Gynecology': Icons.pregnant_woman_rounded,
  'Psychiatry': Icons.self_improvement_rounded,
  'Anesthesiology': Icons.vaccines_rounded,
};

/// The specialist panel at work, while the report is generated: the
/// specialists circle the case, each lighting up as it gives its opinion
/// or fading when it steps aside. It shows only what [progress] says.
class PanelOrbit extends StatefulWidget {
  const PanelOrbit({super.key, required this.progress});

  final ReportProgress? progress;

  @override
  State<PanelOrbit> createState() => _PanelOrbitState();
}

class _PanelOrbitState extends State<PanelOrbit> with TickerProviderStateMixin {
  // One slow turn of the circle, and a quick heartbeat for "thinking".
  late final _spin = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 40),
  )..repeat();
  late final _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1300),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _spin.dispose();
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.progress;
    final stage = p?.stage ?? 'understanding';
    // Before the panel is chosen every case is screened against the whole
    // roster; after, only the specialists actually asked are shown (none
    // when no specialty owns the case).
    final screening =
        p == null ||
        (p.specialists.isEmpty &&
            (stage == 'understanding' || stage == 'evidence'));
    final members = screening
        ? [for (final n in p?.roster ?? const <String>[]) (name: n, state: '')]
        : p.specialists;

    return Column(
      children: [
        LayoutBuilder(
          builder: (context, constraints) {
            final size = math.min(constraints.maxWidth, 560.0);
            return SizedBox(
              width: size,
              height: size,
              child: AnimatedBuilder(
                animation: Listenable.merge([_spin, _pulse]),
                builder: (context, _) =>
                    _orbit(size, stage, members, screening),
              ),
            );
          },
        ),
        const SizedBox(height: 8),
        _Caption(
          progress: p,
          stage: stage,
          shown: screening ? const [] : members,
          roster: screening ? members.length : 0,
        ),
        const SizedBox(height: 22),
        _Steps(stage: stage),
      ],
    );
  }

  Widget _orbit(
    double size,
    String stage,
    List<({String name, String state})> members,
    bool screening,
  ) {
    final node = screening ? 34.0 : 66.0;
    final radius = size / 2 - (screening ? node : node + 22);
    final centre = Offset(size / 2, size / 2);
    final turn = _spin.value * 2 * math.pi;
    final positions = [
      for (var i = 0; i < members.length; i++)
        centre +
            Offset.fromDirection(
              turn + 2 * math.pi * i / members.length - math.pi / 2,
              radius,
            ),
    ];

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned.fill(
          child: CustomPaint(
            painter: _Links(
              centre: centre,
              radius: radius,
              ends: [
                for (final (i, m) in members.indexed)
                  if (m.state == 'thinking' || m.state == 'took_part')
                    (positions[i], m.state == 'thinking'),
              ],
              pulse: _pulse.value,
            ),
          ),
        ),
        Positioned(
          left: centre.dx - 75,
          top: centre.dy - 75,
          child: _Core(stage: stage, pulse: _pulse.value),
        ),
        for (final (i, m) in members.indexed)
          Positioned(
            left: positions[i].dx - (screening ? node / 2 : 60),
            top: positions[i].dy - node / 2,
            child: screening
                ? _Dot(name: m.name, size: node, pulse: _pulse.value, i: i)
                : _Specialist(
                    name: m.name,
                    state: m.state,
                    size: node,
                    pulse: _pulse.value,
                  ),
          ),
      ],
    );
  }
}

/// The case in the middle, with what is happening to it.
class _Core extends StatelessWidget {
  const _Core({required this.stage, required this.pulse});

  final String stage;
  final double pulse;

  @override
  Widget build(BuildContext context) {
    final icon = switch (stage) {
      'understanding' => Icons.record_voice_over_rounded,
      'evidence' => Icons.menu_book_rounded,
      'panel' => Icons.groups_rounded,
      'chair' => Icons.forum_rounded,
      'precautions' => Icons.health_and_safety_rounded,
      'done' => Icons.check_rounded,
      _ => Icons.edit_note_rounded,
    };
    return SizedBox(
      width: 150,
      height: 150,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            width: 130 + 20 * pulse,
            height: 130 + 20 * pulse,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: MedoraColors.primary.withValues(alpha: 0.10),
            ),
          ),
          Container(
            width: 104,
            height: 104,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              gradient: MedoraTheme.brandGradient,
              boxShadow: [
                BoxShadow(
                  color: Color(0x33C8573A),
                  blurRadius: 30,
                  offset: Offset(0, 12),
                ),
              ],
            ),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              child: Icon(
                icon,
                key: ValueKey(icon),
                color: Colors.white,
                size: 46,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A specialty on the roster while the case is being screened.
class _Dot extends StatelessWidget {
  const _Dot({
    required this.name,
    required this.size,
    required this.pulse,
    required this.i,
  });

  final String name;
  final double size;
  final double pulse;
  final int i;

  @override
  Widget build(BuildContext context) {
    // A wave of light passing round the circle: the roster being scanned.
    final glow = (math.sin(pulse * math.pi + i * 0.6) + 1) / 2;
    return Tooltip(
      message: name,
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Color.lerp(
            const Color(0xFFEDE5D8),
            const Color(0xFFF1D3C6),
            glow,
          ),
        ),
        child: Icon(
          specialistIcons[name] ?? Icons.medical_services_rounded,
          size: size * 0.5,
          color: Color.lerp(MedoraColors.muted, MedoraColors.primary, glow),
        ),
      ),
    );
  }
}

/// One specialist the case was sent to, and how far they are.
class _Specialist extends StatelessWidget {
  const _Specialist({
    required this.name,
    required this.state,
    required this.size,
    required this.pulse,
  });

  final String name;
  final String state;
  final double size;
  final double pulse;

  @override
  Widget build(BuildContext context) {
    final aside = state == 'stepped_aside' || state == 'unavailable';
    final done = state == 'took_part';
    final color = done
        ? MedoraColors.teal
        : aside
        ? const Color(0xFFB9B1A4)
        : MedoraColors.primary;
    return SizedBox(
      width: 120,
      child: Column(
        children: [
          AnimatedOpacity(
            duration: const Duration(milliseconds: 400),
            opacity: aside ? 0.55 : 1,
            child: Stack(
              clipBehavior: Clip.none,
              alignment: Alignment.center,
              children: [
                if (state == 'thinking')
                  Container(
                    width: size + 14 + 10 * pulse,
                    height: size + 14 + 10 * pulse,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: MedoraColors.primary.withValues(
                          alpha: 0.5 - 0.35 * pulse,
                        ),
                        width: 2,
                      ),
                    ),
                  ),
                AnimatedContainer(
                  duration: const Duration(milliseconds: 400),
                  width: size,
                  height: size,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: MedoraTheme.tint(color),
                    boxShadow: aside
                        ? null
                        : [
                            BoxShadow(
                              color: color.withValues(alpha: 0.35),
                              blurRadius: 18,
                              offset: const Offset(0, 8),
                            ),
                          ],
                  ),
                  child: Icon(
                    specialistIcons[name] ?? Icons.medical_services_rounded,
                    color: Colors.white,
                    size: size * 0.46,
                  ),
                ),
                if (done || aside)
                  Positioned(
                    right: 0,
                    bottom: 0,
                    child: Container(
                      padding: const EdgeInsets.all(3),
                      decoration: const BoxDecoration(
                        shape: BoxShape.circle,
                        color: Colors.white,
                      ),
                      child: Icon(
                        done ? Icons.check_circle_rounded : Icons.remove_circle,
                        size: 20,
                        color: done ? MedoraColors.teal : MedoraColors.muted,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            S.of(context).specialist(name),
            textAlign: TextAlign.center,
            maxLines: 2,
            style: TextStyle(
              fontSize: 13,
              height: 1.2,
              fontWeight: FontWeight.w700,
              color: aside ? MedoraColors.muted : MedoraColors.text,
            ),
          ),
          Text(
            S.of(context).specialistState(state),
            style: TextStyle(
              fontSize: 11.5,
              color: done ? MedoraColors.teal : MedoraColors.muted,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// The orbit ring, and a line from the case to each specialist at work.
class _Links extends CustomPainter {
  _Links({
    required this.centre,
    required this.radius,
    required this.ends,
    required this.pulse,
  });

  final Offset centre;
  final double radius;
  final List<(Offset, bool)> ends;
  final double pulse;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawCircle(
      centre,
      radius,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..color = MedoraColors.border,
    );
    for (final (end, thinking) in ends) {
      final paint = Paint()
        ..strokeWidth = 2
        ..color = (thinking ? MedoraColors.primary : MedoraColors.teal)
            .withValues(alpha: thinking ? 0.15 + 0.35 * pulse : 0.35);
      canvas.drawLine(centre, end, paint);
    }
  }

  @override
  bool shouldRepaint(_Links old) => true;
}

class _Caption extends StatelessWidget {
  const _Caption({
    required this.progress,
    required this.stage,
    required this.shown,
    required this.roster,
  });

  final ReportProgress? progress;
  final String stage;

  /// The specialists on screen, and how many specialties are screened.
  final List<({String name, String state})> shown;
  final int roster;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final members = shown;
    final answered = members.where((m) => m.state != 'thinking').length;
    final tookPart = members.where((m) => m.state == 'took_part').length;
    final aside = members.where((m) => m.state == 'stepped_aside').length;

    final (title, detail) = switch (stage) {
      'understanding' => (
        s.understanding,
        roster == 0 ? s.preparingCase : s.screening(roster),
      ),
      'evidence' => (s.checkingKnowledge, s.matchingSymptoms),
      // No specialty owns the case: the general physician reviews it.
      'panel' when members.isEmpty => (s.reviewingCase, s.fewMoments),
      'chair' when tookPart == 0 => (s.bringingTogether, ''),
      'panel' => (
        s.specialistsReviewing,
        s.answered(answered, members.length, aside),
      ),
      'chair' => (s.reachingConclusion, s.tookPart(tookPart)),
      'precautions' => (s.writingReport, s.preparingAdvice),
      'done' => (s.reportReady, ''),
      _ => (s.writingSummary, s.fewMoments),
    };
    return Column(
      children: [
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 300),
          child: Text(
            title,
            key: ValueKey(title),
            style: text.headlineSmall?.copyWith(fontSize: 24),
            textAlign: TextAlign.center,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          detail,
          style: text.bodyLarge?.copyWith(color: MedoraColors.muted),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

/// The four steps of a report, ticked off as they finish.
class _Steps extends StatelessWidget {
  const _Steps({required this.stage});

  final String stage;

  @override
  Widget build(BuildContext context) {
    final at = switch (stage) {
      'understanding' => 0,
      'evidence' => 1,
      'panel' || 'chair' || 'writing' => 2,
      'precautions' => 3,
      _ => 4,
    };
    return Wrap(
      alignment: WrapAlignment.center,
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final (i, label) in S.of(context).reportSteps.indexed)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: i < at
                  ? MedoraColors.teal.withValues(alpha: 0.12)
                  : i == at
                  ? MedoraColors.primary.withValues(alpha: 0.12)
                  : Colors.white,
              borderRadius: BorderRadius.circular(30),
              border: Border.all(color: MedoraColors.border),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  i < at
                      ? Icons.check_circle_rounded
                      : i == at
                      ? Icons.autorenew_rounded
                      : Icons.radio_button_unchecked_rounded,
                  size: 18,
                  color: i < at
                      ? MedoraColors.teal
                      : i == at
                      ? MedoraColors.primary
                      : MedoraColors.muted,
                ),
                const SizedBox(width: 6),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: i <= at ? MedoraColors.text : MedoraColors.muted,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
