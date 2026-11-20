import 'package:flutter/material.dart';
import 'package:re_highlight/languages/bash.dart';
import 'package:re_highlight/languages/c.dart';
import 'package:re_highlight/languages/cmake.dart';
import 'package:re_highlight/languages/cpp.dart';
import 'package:re_highlight/languages/css.dart';
import 'package:re_highlight/languages/dart.dart';
import 'package:re_highlight/languages/diff.dart';
import 'package:re_highlight/languages/go.dart';
import 'package:re_highlight/languages/gradle.dart';
import 'package:re_highlight/languages/groovy.dart';
import 'package:re_highlight/languages/java.dart';
import 'package:re_highlight/languages/javascript.dart';
import 'package:re_highlight/languages/json.dart';
import 'package:re_highlight/languages/kotlin.dart';
import 'package:re_highlight/languages/markdown.dart';
import 'package:re_highlight/languages/objectivec.dart';
import 'package:re_highlight/languages/python.dart';
import 'package:re_highlight/languages/ruby.dart';
import 'package:re_highlight/languages/rust.dart';
import 'package:re_highlight/languages/shell.dart';
import 'package:re_highlight/languages/sql.dart';
import 'package:re_highlight/languages/swift.dart';
import 'package:re_highlight/languages/typescript.dart';
import 'package:re_highlight/languages/xml.dart';
import 'package:re_highlight/languages/yaml.dart';
import 'package:re_highlight/re_highlight.dart';
import 'package:re_highlight/styles/github-dark.dart';

/// Syntax highlighter powered by `re_highlight` (Highlight.js v11.9 grammars + GitHub Dark theme).
class QuasarSyntaxHighlighter {
  QuasarSyntaxHighlighter._();

  static const Color defaultColor = Color(0xFFE6EDF3);

  static final Highlight _highlight = _createHighlight();

  // Strip root backgroundColor from githubDarkTheme so diff +/- row tints remain visible.
  static final Map<String, TextStyle> _theme = <String, TextStyle>{
    ...githubDarkTheme,
    'root': const TextStyle(color: defaultColor),
  };

  static Highlight _createHighlight() {
    final Highlight h = Highlight();
    h.registerLanguages(<String, Mode>{
      'bash': langBash,
      'c': langC,
      'cmake': langCmake,
      'cpp': langCpp,
      'css': langCss,
      'dart': langDart,
      'diff': langDiff,
      'go': langGo,
      'gradle': langGradle,
      'groovy': langGroovy,
      'java': langJava,
      'javascript': langJavascript,
      'json': langJson,
      'kotlin': langKotlin,
      'markdown': langMarkdown,
      'objectivec': langObjectivec,
      'python': langPython,
      'ruby': langRuby,
      'rust': langRust,
      'shell': langShell,
      'sql': langSql,
      'swift': langSwift,
      'typescript': langTypescript,
      'xml': langXml,
      'yaml': langYaml,
    });
    return h;
  }

  static String? _normalizeLanguage(String raw) {
    final String l = raw.toLowerCase().trim();
    if (l.isEmpty) return null;
    const Map<String, String> aliases = <String, String>{
      'dart': 'dart',
      'swift': 'swift',
      'kt': 'kotlin',
      'kts': 'kotlin',
      'kotlin': 'kotlin',
      'java': 'java',
      'c': 'c',
      'h': 'cpp',
      'hh': 'cpp',
      'hpp': 'cpp',
      'cc': 'cpp',
      'cpp': 'cpp',
      'cxx': 'cpp',
      'c++': 'cpp',
      'm': 'objectivec',
      'mm': 'objectivec',
      'objc': 'objectivec',
      'objectivec': 'objectivec',
      'objective-c': 'objectivec',
      'py': 'python',
      'python': 'python',
      'js': 'javascript',
      'jsx': 'javascript',
      'mjs': 'javascript',
      'cjs': 'javascript',
      'javascript': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'typescript': 'typescript',
      'rs': 'rust',
      'rust': 'rust',
      'go': 'go',
      'yaml': 'yaml',
      'yml': 'yaml',
      'json': 'json',
      'arb': 'json',
      'sh': 'bash',
      'bash': 'bash',
      'zsh': 'bash',
      'shell': 'shell',
      'cmake': 'cmake',
      'gradle': 'gradle',
      'groovy': 'groovy',
      'xml': 'xml',
      'html': 'xml',
      'svg': 'xml',
      'plist': 'xml',
      'css': 'css',
      'md': 'markdown',
      'markdown': 'markdown',
      'rb': 'ruby',
      'ruby': 'ruby',
      'podspec': 'ruby',
      'sql': 'sql',
      'diff': 'diff',
      'patch': 'diff',
    };
    return aliases[l];
  }

  /// Renders [code] into a syntax-highlighted [TextSpan] using `re_highlight`.
  static TextSpan highlightSpan(
    String code, {
    required TextStyle baseStyle,
    String language = '',
  }) {
    if (code.isEmpty) {
      return TextSpan(text: '', style: baseStyle);
    }
    try {
      final String? lang = _normalizeLanguage(language);
      final HighlightResult result = lang != null
          ? _highlight.highlight(code: code, language: lang)
          : _highlight.highlightAuto(code);
      final TextSpanRenderer renderer = TextSpanRenderer(baseStyle, _theme);
      result.render(renderer);
      return renderer.span ?? TextSpan(text: code, style: baseStyle);
    } catch (_) {
      return TextSpan(text: code, style: baseStyle);
    }
  }

  /// Infers a language name from a file path (e.g. `foo.dart` -> `dart`, `CMakeLists.txt` -> `cmake`).
  static String languageFromPath(String path) {
    final String lower = path.toLowerCase();
    final String base = lower.split('/').last;
    if (base == 'cmakelists.txt') return 'cmake';
    if (base == 'podfile' || base.endsWith('.podspec')) return 'ruby';
    if (base == 'build.gradle' || base.endsWith('.gradle')) return 'gradle';
    final int dot = base.lastIndexOf('.');
    if (dot == -1 || dot == base.length - 1) return '';
    return base.substring(dot + 1);
  }
}
