import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';
import 'admin_widgets.dart';

const _base = '/api/admin/knowledge';

/// The medical knowledge database: what is in it, and how files get in.
class KnowledgeTab extends StatefulWidget {
  const KnowledgeTab({super.key, required this.admin});

  final AdminApi admin;

  @override
  State<KnowledgeTab> createState() => _KnowledgeTabState();
}

class _KnowledgeTabState extends State<KnowledgeTab> with Loader {
  Map<String, dynamic>? _summary;
  List<dynamic> _runs = [];

  // Browse state.
  String _table = 'diseases';
  String _query = '';
  int _offset = 0;
  int _total = 0;
  List<dynamic> _items = [];
  Timer? _searchDebounce;
  String? _uploading;

  static const _pageSize = 25;

  @override
  void dispose() {
    _searchDebounce?.cancel();
    super.dispose();
  }

  @override
  Future<void> load() async {
    _summary = await widget.admin.get('$_base/summary') as Map<String, dynamic>;
    if (_summary!['ready'] != true) return;
    final results = await Future.wait([
      widget.admin.get('$_base/ingest/runs'),
      widget.admin.get(
        '$_base/$_table',
        query: {'q': _query, 'limit': '$_pageSize', 'offset': '$_offset'},
      ),
    ]);
    _runs = results[0] as List;
    final page = results[1] as Map<String, dynamic>;
    _total = page['total'] as int;
    _items = page['items'] as List;
  }

  void _browse({String? table, String? query, int? offset}) {
    _table = table ?? _table;
    _query = query ?? _query;
    _offset = offset ?? 0;
    run(() async {});
  }

  Future<void> _upload() async {
    final picked = await FilePicker.pickFiles();
    if (picked.isEmpty) return;
    final problems = <String>[];
    await run(() async {
      for (final (i, file) in picked.indexed) {
        setState(
          () => _uploading =
              'Uploading and planning ${i + 1} of ${picked.length}: '
              '${file.name}',
        );
        try {
          final bytes = await file.readAsBytes();
          await widget.admin.upload(
            '$_base/ingest/upload',
            filename: file.name,
            bytes: Stream.value(bytes),
            length: bytes.length,
          );
        } on ApiException catch (e) {
          problems.add('${file.name}: ${e.message}');
        }
      }
    });
    if (!mounted) return;
    setState(() {
      _uploading = null;
      if (problems.isNotEmpty) error = problems.join('\n');
    });
  }

  Future<void> _act(int runId, String action, {String? text}) => run(
    () => widget.admin.send(
      'POST',
      '$_base/ingest/runs/$runId/$action',
      body: text == null ? null : {'text': text},
      // Loading a large file, or re-planning with the AI, takes a while.
      timeout: const Duration(minutes: 10),
    ),
  );

  Future<void> _openRun(Map<String, dynamic> run) async {
    final Map<String, dynamic> detail;
    try {
      detail =
          await widget.admin.get('$_base/ingest/runs/${run['id']}')
              as Map<String, dynamic>;
    } on ApiException catch (e) {
      setState(() => error = e.message);
      return;
    }
    if (!mounted) return;
    final action = await showDialog<String>(
      context: context,
      builder: (context) => _RunDialog(run: detail),
    );
    if (action == null || !mounted) return;
    String? text;
    if (action == 'reject' || action == 'revise') {
      text = await askText(
        context,
        title: action == 'reject' ? 'Reject this file' : 'Revise the plan',
        label: action == 'reject'
            ? 'Why should it not be loaded?'
            : 'What should the AI change?',
        hint: action == 'reject'
            ? null
            : 'For example: only add aliases to existing drugs, '
                  'do not create new ones',
        confirm: action == 'reject' ? 'Reject' : 'Revise',
      );
      if (text == null) return;
    }
    await _act(run['id'] as int, action, text: text);
  }

  Future<void> _openDisease(int id) async {
    final Map<String, dynamic> d;
    try {
      d = await widget.admin.get('$_base/diseases/$id') as Map<String, dynamic>;
    } on ApiException catch (e) {
      setState(() => error = e.message);
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => _DiseaseDialog(disease: d),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _summary;
    if (s == null) return Column(children: statusWidgets());
    if (s['ready'] != true) return _notReady(s);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        TileGrid(
          minTileWidth: 170,
          children: [
            StatTile('Diseases', formatCount(s['diseases'] as int)),
            StatTile('Symptoms', formatCount(s['symptoms'] as int)),
            StatTile('Drugs', formatCount(s['drugs'] as int)),
            StatTile(
              'Disease–symptom links',
              formatCount(s['symptomLinks'] as int),
            ),
            StatTile('Disease–drug links', formatCount(s['drugLinks'] as int)),
            StatTile('Precautions', formatCount(s['precautions'] as int)),
          ],
        ),
        const SizedBox(height: 20),
        _ingestion(),
        const SizedBox(height: 20),
        _browser(),
      ],
    );
  }

  Widget _notReady(Map<String, dynamic> s) {
    final legacy = (s['legacyTables'] as List).cast<String>();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        Section(
          title: 'Medical knowledge',
          subtitle: legacy.isEmpty
              ? 'The knowledge tables have not been created in this database.'
              : 'This database has knowledge tables in an older layout '
                    '(${legacy.join(', ')}). Replacing them is done from the '
                    'command line, so it cannot happen by accident.',
          child: legacy.isEmpty
              ? Align(
                  alignment: Alignment.centerLeft,
                  child: FilledButton(
                    onPressed: busy
                        ? null
                        : () => run(
                            () => widget.admin.send('POST', '$_base/init'),
                          ),
                    child: const Text('Create the tables'),
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }

  Widget _ingestion() {
    return Section(
      title: 'Data ingestion',
      subtitle:
          'Upload a file in any format. The AI works out what it contains and '
          'proposes how to load it; nothing is loaded until you approve.',
      actions: [
        FilledButton.icon(
          onPressed: busy ? null : _upload,
          icon: const Icon(Icons.upload_file),
          label: const Text('Upload files'),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_uploading != null) ...[
            MedoraNotice(
              icon: Icons.cloud_upload_outlined,
              message: _uploading!,
              color: MedoraColors.primary,
            ),
            const SizedBox(height: 12),
          ],
          _runs.isEmpty
              ? const EmptyNote('No files have been ingested yet.')
              : ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 420),
                  child: SingleChildScrollView(
                    child: AdminTable(
                      onTap: (i) => _openRun(_runs[i] as Map<String, dynamic>),
                      columns: const ['File', 'Status', 'What it is', 'Result'],
                      rows: [
                        for (final r in _runs)
                          [
                            Clipped(r['filename'] as String, width: 230),
                            _StatusPill(r as Map<String, dynamic>),
                            Clipped(
                              (r['summary'] as String).isNotEmpty
                                  ? r['summary'] as String
                                  : r['note'] as String,
                              width: 360,
                            ),
                            Text(_result(r)),
                          ],
                      ],
                    ),
                  ),
                ),
        ],
      ),
    );
  }

  static String _result(Map<String, dynamic> run) {
    final loaded = run['loaded'] as Map<String, dynamic>?;
    if (loaded != null && run['status'] == 'loaded') {
      final parts = <String>[
        for (final table in const ['diseases', 'symptoms', 'drugs'])
          if ((loaded[table]?['created'] ?? 0) > 0)
            '${formatCount(loaded[table]['created'] as int)} $table',
        if ((loaded['links']?['created'] ?? 0) > 0)
          '${formatCount(loaded['links']['created'] as int)} links',
        if ((loaded['precautions']?['created'] ?? 0) > 0)
          '${formatCount(loaded['precautions']['created'] as int)} precautions',
      ];
      return parts.isEmpty
          ? 'Enriched existing rows'
          : 'Added ${parts.join(', ')}';
    }
    return '';
  }

  Widget _browser() {
    final last = (_offset + _items.length);
    return Section(
      title: 'Browse the knowledge',
      actions: [
        SegmentedButton<String>(
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: 'diseases', label: Text('Diseases')),
            ButtonSegment(value: 'symptoms', label: Text('Symptoms')),
            ButtonSegment(value: 'drugs', label: Text('Drugs')),
          ],
          selected: {_table},
          onSelectionChanged: (s) => _browse(table: s.first, query: ''),
        ),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            key: ValueKey(_table),
            decoration: const InputDecoration(
              labelText: 'Search by name or alias',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (value) {
              _searchDebounce?.cancel();
              _searchDebounce = Timer(
                const Duration(milliseconds: 350),
                () => _browse(query: value),
              );
            },
          ),
          const SizedBox(height: 12),
          _items.isEmpty
              ? const EmptyNote('Nothing matches.')
              : AdminTable(
                  onTap: _table == 'diseases'
                      ? (i) => _openDisease(_items[i]['id'] as int)
                      : null,
                  columns: [
                    'Name',
                    'Also known as',
                    _table == 'diseases' ? 'Links' : 'Diseases',
                    switch (_table) {
                      'drugs' => 'Used for',
                      _ => 'Description',
                    },
                  ],
                  rows: [
                    for (final item in _items)
                      [
                        Clipped(item['name'] as String, width: 240),
                        Clipped(
                          (item['aliases'] as List).join(', '),
                          width: 220,
                        ),
                        Text(formatCount(item['links'] as int)),
                        Clipped(
                          (item[_table == 'drugs' ? 'uses' : 'description'] ??
                                  '')
                              as String,
                          width: 380,
                        ),
                      ],
                  ],
                ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Text(
                _total == 0
                    ? ''
                    : '${formatCount(_offset + 1)}–${formatCount(last)} '
                          'of ${formatCount(_total)}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              IconButton(
                tooltip: 'Previous page',
                onPressed: busy || _offset == 0
                    ? null
                    : () => _browse(offset: _offset - _pageSize),
                icon: const Icon(Icons.chevron_left),
              ),
              IconButton(
                tooltip: 'Next page',
                onPressed: busy || last >= _total
                    ? null
                    : () => _browse(offset: _offset + _pageSize),
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill(this.run);

  final Map<String, dynamic> run;

  @override
  Widget build(BuildContext context) {
    final review = (run['needsReview'] as List).isNotEmpty;
    final (label, color) = switch (run['status']) {
      'planned' when review => ('Needs review', MedoraColors.warning),
      'planned' => ('Waiting for approval', MedoraColors.primary),
      'approved' => ('Approved', MedoraColors.primary),
      'loaded' => ('Loaded', MedoraColors.teal),
      'failed' => ('Failed', MedoraColors.danger),
      'undone' => ('Undone', MedoraColors.muted),
      _ => (
        run['verdict'] == 'not_data' ? 'Not data' : 'Skipped',
        MedoraColors.muted,
      ),
    };
    return Pill(label, color);
  }
}

/// One ingestion run: the AI's plan, what it would do, and what to do next.
class _RunDialog extends StatelessWidget {
  const _RunDialog({required this.run});

  final Map<String, dynamic> run;

  static String _col(Map? col) {
    if (col == null) return '';
    final split = col['split'] == null ? '' : ' (split on "${col['split']}")';
    return '${(col['sources'] as List).join(' or ')}$split';
  }

  static String _mapping(Map<String, dynamic> o) {
    switch (o['kind']) {
      case 'entity':
        final fields = (o['fields'] as Map).entries
            .map((e) => '${e.key} ← ${_col(e.value as Map)}')
            .join(', ');
        final mode = o['mode'] == 'enrich_only'
            ? 'Enrich existing ${o['table']} only'
            : 'Add ${o['table']}';
        return '$mode: name ← ${_col(o['name'] as Map)}'
            '${o['aliases'] == null ? '' : ', aliases ← ${_col(o['aliases'] as Map)}'}'
            '${fields.isEmpty ? '' : ', $fields'}';
      case 'link':
        final target = o['symptom'] != null ? 'symptom' : 'drug';
        return 'Link disease ← ${_col(o['disease'] as Map)}  to  '
            '$target ← ${_col(o[target] as Map)}';
      default:
        return 'Precaution ← ${_col(o['text'] as Map)} '
            'for ${o['disease'] != null ? 'disease ← ${_col(o['disease'] as Map)}' : 'symptom ← ${_col(o['symptom'] as Map)}'}';
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final status = run['status'] as String;
    final stats =
        (run['loaded'] == null ? run['preview'] : null)
            as Map<String, dynamic>?;
    final review = (run['needsReview'] as List).cast<String>();
    final outputs = (run['outputs'] as List).cast<Map<String, dynamic>>();
    final rejects = (run['rejects'] as List).cast<Map<String, dynamic>>();
    final dropped = (run['droppedNotInArticle'] as List).cast<String>();
    final usable = run['verdict'] == 'usable';

    Widget heading(String label) => Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 6),
      child: Text(label, style: text.titleMedium),
    );

    return AlertDialog(
      title: Text(run['filename'] as String),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 10,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  _StatusPill(run),
                  Text(
                    '${formatBytes(run['sizeBytes'] as int)}  ·  '
                    'AI confidence ${((run['confidence'] as num) * 100).round()}%',
                    style: text.bodyMedium,
                  ),
                ],
              ),
              if ((run['note'] as String).isNotEmpty) ...[
                const SizedBox(height: 12),
                MedoraNotice(
                  icon: Icons.info_outline,
                  message: run['note'] as String,
                ),
              ],
              for (final r in review) ...[
                const SizedBox(height: 12),
                MedoraNotice(icon: Icons.flag_outlined, message: r),
              ],
              heading('What the AI found'),
              Text(run['summary'] as String),
              if ((run['reason'] as String).isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(run['reason'] as String, style: text.bodyMedium),
              ],
              if (run['content'] == 'article') ...[
                heading('How it will be loaded'),
                const Text(
                  'An article about one disease: the AI extracted its '
                  'description, causes, symptoms, drugs and precautions.',
                ),
              ] else if (outputs.isNotEmpty) ...[
                heading('How it will be loaded'),
                for (final o in outputs)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('•  ${_mapping(o)}'),
                  ),
              ],
              if (stats != null) ...[
                heading(
                  'Preview (first ${formatCount(stats['records'] as int)} records)',
                ),
                Text(
                  '${formatCount(stats['diseases'] as int)} diseases, '
                  '${formatCount(stats['symptoms'] as int)} symptoms, '
                  '${formatCount(stats['drugs'] as int)} drugs, '
                  '${formatCount(stats['links'] as int)} links, '
                  '${formatCount(stats['precautions'] as int)} precautions. '
                  '${((stats['reject_rate'] as num) * 100).toStringAsFixed(1)}% '
                  'of values refused by validation.',
                ),
              ],
              if (dropped.isNotEmpty) ...[
                heading('Dropped: not found in the article'),
                Text(dropped.join('; '), style: text.bodyMedium),
              ],
              if (rejects.isNotEmpty) ...[
                heading('Sample of refused values'),
                for (final r in rejects.take(12))
                  Text(
                    '${r['reason']}: ${r['value']}',
                    style: text.bodyMedium?.copyWith(fontSize: 13),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        if (status != 'loaded')
          TextButton(
            onPressed: () => Navigator.pop(context, 'reject'),
            child: const Text(
              'Reject',
              style: TextStyle(color: MedoraColors.danger),
            ),
          ),
        if (status != 'loaded' && run['content'] != 'article')
          TextButton(
            onPressed: () => Navigator.pop(context, 'revise'),
            child: const Text('Revise plan'),
          ),
        if (usable && const {'planned', 'failed', 'undone'}.contains(status))
          FilledButton(
            onPressed: () => Navigator.pop(context, 'approve'),
            child: const Text('Approve'),
          ),
        if (status == 'approved')
          FilledButton(
            onPressed: () => Navigator.pop(context, 'load'),
            child: const Text('Load into database'),
          ),
        if (status == 'loaded')
          TextButton(
            onPressed: () => Navigator.pop(context, 'undo'),
            child: const Text(
              'Undo this load',
              style: TextStyle(color: MedoraColors.danger),
            ),
          ),
      ],
    );
  }
}

class _DiseaseDialog extends StatelessWidget {
  const _DiseaseDialog({required this.disease});

  final Map<String, dynamic> disease;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;

    List<Widget> block(String label, String body) => body.isEmpty
        ? const []
        : [
            Padding(
              padding: const EdgeInsets.only(top: 14, bottom: 4),
              child: Text(label, style: text.titleMedium),
            ),
            Text(body),
          ];

    final symptoms = (disease['symptoms'] as List).cast<String>();
    final drugs = (disease['drugs'] as List).cast<String>();
    final precautions = (disease['precautions'] as List).cast<String>();
    return AlertDialog(
      title: Text(disease['name'] as String),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ...block(
                'Also known as',
                (disease['aliases'] as List).join(', '),
              ),
              ...block('Description', disease['description'] as String),
              ...block('Causes', disease['causes'] as String),
              ...block('Symptoms (${symptoms.length})', symptoms.join(', ')),
              ...block('Drugs (${drugs.length})', drugs.join(', ')),
              ...block(
                'Precautions (${precautions.length})',
                precautions.map((p) => '•  $p').join('\n'),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
