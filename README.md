# AI Voice Changer

Экспериментальное локальное приложение для Windows: мужской → женский голос.
Python 3.11, PyTorch/CUDA, PySide6, нативный C++20/WASAPI.

## Скачать полную программу для Windows

Скачайте установщик и все четыре части данных в одну папку, затем запустите **AI-Voice-Changer-Setup-0.3.1.exe**. Комплект включает Python, модели и CUDA-библиотеки; общий размер около 6,58 ГБ.

- [AI-Voice-Changer-Setup-0.3.1.exe](https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/v0.3.1/AI-Voice-Changer-Setup-0.3.1.exe)
- [AI-Voice-Changer-Setup-0.3.1-1.bin](https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/v0.3.1/AI-Voice-Changer-Setup-0.3.1-1.bin)
- [AI-Voice-Changer-Setup-0.3.1-2.bin](https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/v0.3.1/AI-Voice-Changer-Setup-0.3.1-2.bin)
- [AI-Voice-Changer-Setup-0.3.1-3.bin](https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/v0.3.1/AI-Voice-Changer-Setup-0.3.1-3.bin)
- [AI-Voice-Changer-Setup-0.3.1-4.bin](https://github.com/friendzonebycarefree/ai-voice-changer/releases/download/v0.3.1/AI-Voice-Changer-Setup-0.3.1-4.bin)

Установка, запуск установленного EXE, диагностика WASAPI и удаление проверены на машине разработки. Драйвер NVIDIA и VB-CABLE устанавливаются отдельно при необходимости.

## Версия 0.3.1

Один экран: **качество, вход, выход, запуск**. На NVIDIA — микрофон и устройство
вывода (для Discord выберите CABLE Input, в Discord — CABLE Output).
Без CUDA также доступны микрофон и наушники: обработка выполняется на CPU с возможной заметной задержкой. Файловый режим не подставляется автоматически.

Прогрев идёт в worker, интерфейс продолжает обрабатывать события, остановка доступна.
Если обработка занимает 193 мс при прежнем блоке 180 мс, блок автоматически
увеличивается до 260 мс. Ограничение подбора — 400 мс. Медленный прогрев и отставание не останавливают
программу: она продолжает с задержкой и предупреждением. Старые входные фрагменты
при переполнении ограниченной очереди пропускаются, память не растёт бесконечно. Больший буфер повышает задержку, это не обещание e2e≤200 мс.

## Маленькое обновление для установленной оптимизированной версии

Скачайте **update-0.3.1.zip** из [Releases](https://github.com/friendzonebycarefree/ai-voice-changer/releases/latest).
Закройте программу через «Завершить» в трее. Распакуйте архив рядом с
**VoiceChanger.exe** и запустите **Обновить.cmd**. Сохраните структуру payload.
Обновление проверяет SHA-256 всех файлов и совместимость моделей до записи;
при ошибке замены возвращает старые файлы. Модели и CUDA не скачиваются заново.
Пакет подходит к оптимизированной установке с папкой app и закреплённым manifest.
Это патч, не комплект для первой установки.

После 0.3.1: пункт «Проверить обновления» в трее скачивает только небольшой ZIP.
Закройте и откройте программу, чтобы применить его до загрузки GUI и аудиодвижка.
Обновления запрашиваются только по этой команде. Для конверсии интернет не нужен.

## Исходники и проверка

Для сборки нужен полный исходный runtime/model-комплект установленной версии,
Python 3.11 и Visual Studio C++ Build Tools. Скопируйте app/models в models,
установите source/requirements.txt и выполните source/native/build.ps1.
Тесты: PYTHONPATH=source; python -m unittest discover -s source/tests -v.
Нейросетевой тест дополнительно использует публичный samples/ru-original.wav
из полного комплекта. Конфигурации и хеши моделей находятся в models/manifest.json.
Весов и CUDA-библиотек в Git нет. Сборка portable: source/build.ps1.

Автотесты проверяют регрессию прогрева, отзывчивость event loop, безопасность
обновления, живой CPU-поток без CUDA, ограниченные очереди и настоящий Seed-VC forward.
На машине разработки нет NVIDIA: исправление проверено тестами планировщика,
файловой конверсией и GUI. Аппаратная CUDA/VB-CABLE, MOS и двухчасовой тест
ещё требуют приёмки. Метрики модели не выдаются за сквозную задержку.

GPL-3.0. См. LICENSE, ATTRIBUTION.md и сохранённые vendor notices.
