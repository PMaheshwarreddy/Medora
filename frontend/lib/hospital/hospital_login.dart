import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart' show ApiException;
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart'
    show BrandMark, MedoraCard, MedoraNotice;
import 'hospital_api.dart';
import 'hospital_session.dart';

/// Signing in to the hospital portal, with the hospital account the
/// hospital's administrator (or Medora) created.
class HospitalLogin extends ConsumerStatefulWidget {
  const HospitalLogin({
    super.key,
    required this.session,
    this.title = 'Hospital portal',
  });

  /// Which portal is being signed in to.
  final PortalSession session;
  final String title;

  @override
  ConsumerState<HospitalLogin> createState() => _HospitalLoginState();
}

class _HospitalLoginState extends ConsumerState<HospitalLogin> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final client = ref.read(hospitalClientProvider);
    try {
      final body = await client.login(_email.text.trim(), _password.text);
      ref
          .read(widget.session.notifier)
          .signIn(
            HospitalApi(
              client,
              body['token'] as String,
              (body['user'] as Map).cast<String, dynamic>(),
              (body['hospital'] as Map).cast<String, dynamic>(),
            ),
          );
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    return _Centered(
      title: widget.title,
      subtitle: 'Sign in with your hospital account.',
      children: [
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 16),
        ],
        TextField(
          key: const Key('hospital-email'),
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(
            labelText: 'Email',
            prefixIcon: Icon(Icons.mail_outline_rounded),
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('hospital-password'),
          controller: _password,
          obscureText: true,
          onSubmitted: (_) => _submit(),
          decoration: const InputDecoration(
            labelText: 'Password',
            prefixIcon: Icon(Icons.lock_outline_rounded),
          ),
        ),
        const SizedBox(height: 22),
        FilledButton(
          key: const Key('hospital-sign-in'),
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? 'Signing in…' : 'Sign in'),
        ),
        const SizedBox(height: 14),
        Text(
          'Forgot your password? Ask your hospital\'s administrator to reset it.',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 13),
        ),
      ],
    );
  }
}

/// Choosing one's own password after signing in with a temporary one.
class HospitalPasswordChange extends ConsumerStatefulWidget {
  const HospitalPasswordChange({super.key, required this.session});

  final PortalSession session;

  @override
  ConsumerState<HospitalPasswordChange> createState() =>
      _HospitalPasswordChangeState();
}

class _HospitalPasswordChangeState
    extends ConsumerState<HospitalPasswordChange> {
  final _current = TextEditingController();
  final _new = TextEditingController();
  final _again = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_current, _new, _again]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (_new.text != _again.text) {
      setState(() => _error = 'The two new passwords are not the same.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = ref.read(widget.session)!;
    try {
      await api.send(
        'POST',
        '/auth/password',
        body: {'current': _current.text, 'new': _new.text},
      );
      ref
          .read(widget.session.notifier)
          .update(
            api.copyWith(user: {...api.user, 'mustChangePassword': false}),
          );
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(widget.session)!;
    return _Centered(
      title: 'Choose your password',
      subtitle:
          'Welcome, ${api.user['name']}. You signed in with a temporary '
          'password; choose your own to continue.',
      children: [
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 16),
        ],
        TextField(
          key: const Key('password-current'),
          controller: _current,
          obscureText: true,
          decoration: const InputDecoration(labelText: 'Temporary password'),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('password-new'),
          controller: _new,
          obscureText: true,
          decoration: const InputDecoration(
            labelText: 'New password (at least 8 characters)',
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          key: const Key('password-again'),
          controller: _again,
          obscureText: true,
          onSubmitted: (_) => _submit(),
          decoration: const InputDecoration(labelText: 'New password again'),
        ),
        const SizedBox(height: 22),
        FilledButton(
          key: const Key('password-save'),
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? 'Saving…' : 'Save and continue'),
        ),
        TextButton(
          onPressed: () => ref.read(widget.session.notifier).signOut(),
          child: const Text('Sign out'),
        ),
      ],
    );
  }
}

class _Centered extends StatelessWidget {
  const _Centered({
    required this.title,
    required this.subtitle,
    required this.children,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      backgroundColor: MedoraColors.background,
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: MedoraCard(
              padding: const EdgeInsets.all(30),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Row(
                    children: [
                      BrandMark(size: 40),
                      SizedBox(width: 10),
                      Text(
                        'Medora',
                        style: TextStyle(
                          fontFamily: MedoraFonts.serif,
                          fontSize: 22,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Text(title, style: text.headlineSmall),
                  const SizedBox(height: 6),
                  Text(subtitle, style: text.bodyMedium),
                  const SizedBox(height: 22),
                  ...children,
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
