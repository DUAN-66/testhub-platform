module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true
  },
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-essential',
    '@vue/eslint-config-prettier/skip-formatting'
  ],
  parserOptions: {
    parser: '@typescript-eslint/parser',
    ecmaVersion: 'latest',
    sourceType: 'module'
  },
  rules: {
    // Phase 0 先建立可运行的只读检查，历史存量在后续迭代逐步收紧。
    'no-unused-vars': 'off',
    'no-undef': 'off',
    'no-dupe-keys': 'warn',
    'no-empty': 'warn',
    'no-constant-condition': 'warn',
    'no-useless-catch': 'warn',
    'no-useless-escape': 'warn',
    'vue/multi-word-component-names': 'off',
    'vue/no-unused-components': 'warn',
    'vue/no-mutating-props': 'warn',
    'vue/no-unused-vars': 'warn',
    'vue/no-duplicate-attributes': 'warn',
    'vue/no-ref-as-operand': 'warn'
  }
}
