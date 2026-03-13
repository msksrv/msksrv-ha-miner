# Submit these brand assets to Home Assistant for HACS icon

To show the **MSKSRV ASIC Miner** icon in the HACS store, add them to the official brands repo (one-time).

## Быстрый способ (GitHub UI)

1. Открой **https://github.com/home-assistant/brands**.
2. Нажми **Fork** (создай форк под своим аккаунтом).
3. В своём форке зайди в папку **`custom_integrations`**.
4. Нажми **Add file → Create new file**.
5. Имя файла: **`miner/icon.png`** (папка создастся автоматически).
6. Вставь содержимое файла **`brands_submission/custom_integrations/miner/icon.png`** (скачай из этого репо или открой локально и перетащи в браузер — GitHub позволит загрузить бинарный файл через drag-and-drop при создании).
7. Нажми **Commit new file**.
8. Аналогично создай **`miner/logo.png`** (в той же папке `miner`).
9. Открой **Pull request** из своего форка в **home-assistant/brands**, ветка **master**. Заголовок: **Add miner custom integration brand (MSKSRV ASIC Miner)**.

## Через Git (если удобнее)

1. **Форкни** [home-assistant/brands](https://github.com/home-assistant/brands).
2. **Клонируй свой форк** и зайди в папку:
   ```bash
   git clone https://github.com/YOUR_USERNAME/brands.git
   cd brands
   ```
3. **Создай ветку и скопируй файлы** (из папки с репо msksrv-ha-miner):
   ```bash
   git checkout -b add-miner-custom-integration
   mkdir -p custom_integrations/miner
   cp /path/to/msksrv-ha-miner/brands_submission/custom_integrations/miner/* custom_integrations/miner/
   git add custom_integrations/miner
   git commit -m "Add miner custom integration brand (MSKSRV ASIC Miner)"
   git push origin add-miner-custom-integration
   ```
4. **Открой PR**: https://github.com/home-assistant/brands/compare — выбери свой форк и ветку `add-miner-custom-integration`.

## Требования (home-assistant/brands)

- `icon.png`: 256×256 px (или 512×512 для `icon@2x.png`).
- `logo.png`: короткая сторона 128–256 px.
- PNG, прозрачный фон предпочтителен.

После мержа PR иконка будет подхватываться HACS и CDN брендов для интеграции `miner`.
