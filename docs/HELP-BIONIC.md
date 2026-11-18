# Справка: Bionic Immitator и Pulsar

**Назначение:** программно-физический имитатор установки Bionic Mini. При работе с настоящей платой выступает набором RS-485 устройств, моделирует баки, уровни, насосы, давление, освещение, PonicPilot и ошибки. Не является новым контроллером.

## Без подключённого контроллера (первый запуск)
Windows:
```powershell
bionic-immitator --home .\bionic-data --no-controller
```
Linux:
```bash
bionic-immitator --home ./bionic-data --no-controller
```
Этот режим не открывает USB №1.

## С контроллером
```powershell
bionic-immitator --home .\bionic-data
```
Предварительно настройте порты на странице `view settings`, примените `settings apply` и сохраните `settings save`. Не используйте общую шину одновременно с отдельной программой-master. USB №1 и отдельный USB №2 (Waveshare датчиков уровня) имеют разные роли.

## Справка и разделы
```text
help
status
view settings
view equipment
view pressure
view light
```
Доступны также страницы баков, насосов, PonicPilot, датчиков и журнала. Используйте Tab, PgUp/PgDn, стрелки и F1–F6.

## Пассивная диагностика счётчика Pulsar
```text
counter check start
counter check status
counter check stop
```
Результаты сохраняются в `counter-check-reports`. Эмуляция счётчика Pulsar `N00014163` выключена по умолчанию. Перед включением установите **реальный восьмизначный BCD-адрес**:
```text
settings set pulsar_address 17440707
settings set pulsar_enabled true
settings apply
settings save
```
`17440707` приведён исключительно как пример; не принимайте его за адрес вашего прибора.

## Сохранность данных
`bionic-immitator.ini` хранит настройки, `bionic-runtime-state.json` — текущее физическое состояние модели между запусками. Контроллерные команды DO/AO/RUN из runtime-файла не восстанавливаются. Сброс модели возможен только явной командой `sim reset --confirm`.

Детальное руководство: [BIONIC-IMMITATOR-USER-GUIDE.md](BIONIC-IMMITATOR-USER-GUIDE.md), описание архитектуры [BIONIC-IMMITATOR.md](../BIONIC-IMMITATOR.md).
