# Notices and source attribution

Combined application: GPL-3.0; full license in LICENSE-APP.txt. No warranty.
First-party integration and modifications: Local Voice Changer Project, 2026.

- Seed-VC code: https://github.com/Plachtaa/seed-vc at
  51383efd921027683c89e5348211d93ff12ac2a8, GPL-3.0.
  Inference subset included in source/voicechanger/vendor/seed.
  Changes: lazy optional quantizer import; load n_codebooks from config; safe checkpoint
  compatibility for deterministic position/frequency buffers; cancellation and progress
  per diffusion step; removed console tqdm. Trainable checkpoint parameters are verified.
- Seed Tiny weights: https://huggingface.co/Plachta/Seed-VC at
  257283f9f41585055e8f858fba4fd044e5caed6e, publisher GPL-3.0.
- XLSR: https://huggingface.co/facebook/wav2vec2-xls-r-300m, Apache-2.0.
- CAMPPlus: https://huggingface.co/funasr/campplus, Apache-2.0.
- HiFT: https://huggingface.co/FunAudioLLM/CosyVoice-300M, Apache-2.0.
- RVC inference code: Koe AI minimal_rvc from https://github.com/KoeAI/LLVC at
  1627c5d358cf9bb2b92b0ccc513d8b36807c923d, MIT (LICENSE-RVC.txt).
  Inference subset has local imports and omits training helpers.
- RVC voice 8312 and RMVPE weights: https://huggingface.co/KoeAI/llvc_models at
  ebfe8c0fdeb974a7eeb463b3abbc8ce42a0e3851, publisher MIT.
- ContentVec: https://huggingface.co/lengyue233/content-vec-best, publisher MIT.
  Exact revisions, sizes and SHA-256 of all model assets are in models/manifest.json.
- Seed transformer code retains upstream Meta gpt-fast BSD notices where supplied.
- Reference models/references/natural.wav: LibriSpeech speaker 1919, utterance
  1919-142785-0000, via KoeAI/LLVC test_wavs at commit above. LibriSpeech by Vassil
  Panayotov, Daniel Povey and collaborators, https://www.openslr.org/12/, CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/ . Conversion outputs are derivatives,
  not original speech by the target speaker.
- samples/ru-original.wav: Google FLEURS ru_ru/test id1917, male per dataset metadata.
  https://huggingface.co/datasets/google/fleurs, CC BY 4.0. Authors: Alexis Conneau,
  Min Ma, Simran Khanuja, Yu Zhang, Vera Axelrod, Siddharth Dalmia, Jason Riesa,
  Clara Rivera and Ankur Bapna. Transcript is in ru-original-metadata.json.
  natural-female-ru.wav is the raw Seed candidate; natural-female-app.wav is the
  final application's converted derivative, not a recording of the reference speaker.
- Runtime CPython: PSF License; Python license is included with runtime.
- PyTorch/torchaudio, Transformers, Hugging Face Hub, NumPy, SciPy, librosa and other
  dependencies: included wheel .dist-info licenses and runtime-manifest.json.
- Python-SoXR BSD-3-Clause; libsoxr LGPL-2.1-or-later. See included package notices,
  https://github.com/dofuuz/python-soxr and https://sourceforge.net/projects/soxr/ .
- Qt/PySide6/Shiboken: LGPL-3.0/GPL/commercial as applicable to supplied modules.
  https://doc.qt.io/qtforpython-6/licenses.html . Shared libraries remain replaceable;
  application source and rebuild scripts are included. Corresponding upstream sources:
  https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://download.qt.io/official_releases/qt/ .

VB-CABLE is separate, not redistributed: https://vb-audio.com/Services/licensing.htm .
Published license metadata is recorded; no independent commercial-release or likeness-rights
review is claimed. Use only voices and recordings you are authorized to process.
