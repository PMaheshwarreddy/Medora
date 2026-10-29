import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../kiosk/kiosk_key_store.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';
import 'admin_widgets.dart';

/// Sign in to the back office, or create an account for it.
class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _registering = false;
  bool _busy = false;
  bool _showPassword = false;
  String? _error;
  // Shown after registering an account that still needs approval.
  String? _notice;

  @override
  void dispose() {
    for (final c in [_name, _email, _password, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  void _switchMode() => setState(() {
    _registering = !_registering;
    _error = null;
    _notice = null;
    _confirm.clear();
  });

  Future<void> _submit() async {
    if (_busy || !_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    final api = ref.read(apiClientProvider);
    final email = _email.text.trim();
    try {
      final result = _registering
          ? await api.register(_name.text.trim(), email, _password.text)
          : await api.login(email, _password.text);
      final token = result['token'] as String?;
      if (token == null) {
        // Registered, but an administrator has to approve the account.
        _password.clear();
        _confirm.clear();
        _registering = false;
        _notice =
            'Your account has been created. An administrator has to approve '
            'it before you can sign in.';
      } else {
        saveSessionToken(token);
        ref
            .read(adminSessionProvider.notifier)
            .unlock(
              AdminApi(api, token, result['user'] as Map<String, dynamic>),
            );
        return;
      }
    } on ApiException catch (e) {
      _error = e.message;
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final wide = MediaQuery.sizeOf(context).width >= 980;
    final form = Form(
      key: _form,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!wide) ...[
            const Align(
              alignment: Alignment.centerLeft,
              child: BrandMark(size: 52),
            ),
            const SizedBox(height: 20),
          ],

          Text(
            _registering ? 'Create your account' : 'Sign in to Medora',
            style: text.headlineSmall,
          ),
          const SizedBox(height: 28),
          if (_registering) ...[
            TextFormField(
              key: const ValueKey('name'),
              controller: _name,
              textCapitalization: TextCapitalization.words,
              autofillHints: const [AutofillHints.name],
              decoration: const InputDecoration(labelText: 'Full name'),
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Enter your name' : null,
            ),
            const SizedBox(height: 14),
          ],
          TextFormField(
            key: const ValueKey('email'),
            controller: _email,
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            autofillHints: const [AutofillHints.email],
            decoration: const InputDecoration(labelText: 'Email'),
            validator: (v) =>
                RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(v?.trim() ?? '')
                ? null
                : 'Enter a valid email address',
          ),
          const SizedBox(height: 14),
          TextFormField(
            key: const ValueKey('password'),
            controller: _password,
            obscureText: !_showPassword,
            autofillHints: [
              _registering ? AutofillHints.newPassword : AutofillHints.password,
            ],
            decoration: InputDecoration(
              labelText: 'Password',
              helperText: _registering ? 'At least 8 characters' : null,
              suffixIcon: IconButton(
                tooltip: _showPassword ? 'Hide password' : 'Show password',
                icon: Icon(
                  _showPassword
                      ? Icons.visibility_off_outlined
                      : Icons.visibility_outlined,
                ),
                onPressed: () => setState(() => _showPassword = !_showPassword),
              ),
            ),
            validator: (v) {
              if (v == null || v.isEmpty) return 'Enter a password';
              if (_registering && v.length < 8) {
                return 'Use at least 8 characters';
              }
              return null;
            },
            onFieldSubmitted: (_) {
              if (!_registering) _submit();
            },
          ),
          if (_registering) ...[
            const SizedBox(height: 14),
            TextFormField(
              key: const ValueKey('confirm'),
              controller: _confirm,
              obscureText: !_showPassword,
              decoration: const InputDecoration(labelText: 'Confirm password'),
              validator: (v) =>
                  v == _password.text ? null : 'The passwords do not match',
              onFieldSubmitted: (_) => _submit(),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 14),
            MedoraNotice(icon: Icons.error_outline, message: _error!),
          ],
          if (_notice != null) ...[
            const SizedBox(height: 14),
            MedoraNotice(
              icon: Icons.hourglass_top,
              message: _notice!,
              color: MedoraColors.primary,
            ),
          ],
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_registering ? 'Create account' : 'Sign in'),
          ),
          const SizedBox(height: 10),
          TextButton(
            onPressed: _busy ? null : _switchMode,
            child: Text(
              _registering ? 'I already have an account' : 'Create an account',
            ),
          ),
        ],
      ),
    );

    final panel = Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(28),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: wide
              ? form
              : MedoraCard(padding: const EdgeInsets.all(28), child: form),
        ),
      ),
    );

    return Scaffold(
      backgroundColor: MedoraColors.surface,
      body: wide
          ? Row(
              children: [
                const Expanded(flex: 11, child: _BrandPanel()),
                Expanded(flex: 10, child: panel),
              ],
            )
          : DecoratedBox(
              decoration: const BoxDecoration(
                gradient: MedoraTheme.nightGradient,
              ),
              child: panel,
            ),
    );
  }
}

/// The brand side of the sign-in screen: the mark and the name, nothing more.
class _BrandPanel extends StatelessWidget {
  const _BrandPanel();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(gradient: MedoraTheme.nightGradient),
      child: const Stack(
        children: [
          // Two soft glows give the dark panel depth.
          Positioned(
            right: -140,
            top: -120,
            child: _Glow(size: 460, color: Color(0x33C8573A)),
          ),
          Positioned(
            left: -160,
            bottom: -180,
            child: _Glow(size: 520, color: Color(0x40C8573A)),
          ),
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                BrandMark(size: 96),
                SizedBox(height: 28),
                Text(
                  'Medora',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 56,
                    height: 1,
                    fontFamily: MedoraFonts.serif,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -1.6,
                  ),
                ),
                SizedBox(height: 14),
                Text(
                  'Digital healthcare',
                  style: TextStyle(
                    color: Color(0xFFC9D6CE),
                    fontSize: 22,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0.4,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(colors: [color, color.withValues(alpha: 0)]),
      ),
    );
  }
}
