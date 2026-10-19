# Приватный GitHub и защита основной ветки

Удалённый репозиторий не является зависимостью поиска и локальной проверки.
Для общей опубликованной базы нужен приватный `team-memory` и отдельные рабочие ветки.
Сейчас удалённый репозиторий не настроен. Не считать файл конфигурации доказательством
действующей защиты: после применения прочитать настройки обратно через GitHub.

## Первое размещение

После входа `gh auth login` и выбора владельца:

```sh
gh repo create OWNER/team-memory --private --source . --remote origin
git push -u origin main
git push -u origin feature/team-memory-v1
gh pr create --base main --head feature/team-memory-v1 --draft --title 'Team Memory v1' --body-file docs/initial-pr.md
```

`main` в локальном bootstrap содержит только пустой начальный коммит. Единственное
начальное размещение пустой ветки создаёт base для первого PR; код и данные находятся
в рабочей ветке. Если remote уже существует или main содержит данные, эти команды
не использовать вслепую: получить состояние, сверить историю и создать PR к нему.
Переписывание удалённой main не допускается. При первом PR workflow может потребовать
разрешения GitHub на запуск; проверить фактический результат.

## Защита

После появления проверки `validate` применить защиту main:

```sh
gh api --method PUT repos/OWNER/team-memory/branches/main/protection --input .github/main-protection.json
gh api repos/OWNER/team-memory/branches/main/protection
```

Настройки требуют PR с одним одобрением, актуальный base, успешный `validate`,
новое одобрение после push, разрешённые обсуждения и запрещают force push/удаление.
Защита распространяется на администраторов. Сервисной учётной записи агента не выдавать
право обхода; reviewer — человек, отличный от автора PR. Если GitHub отклоняет защиту
из-за прав/тарифа, база не считается готовой к командной публикации: сначала устранить
причину, не ослаблять правило молча.

GitHub approval сам по себе не доказывает, что reviewer — человек, и CI не проверяет
смысл. Команда назначает человеческих reviewers и сверяет SHA по процедуре
[git-workflow](../skills/team-memory/references/git-workflow.md) прямо перед merge.
При сдвиге base повторный запрос агенту: «Сверь PR с актуальной main, обнови ветку и SHA
смысловой проверки». Merge остаётся человеческим действием.

Поля конфигурации основаны на [GitHub REST API branch protection](https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection).
