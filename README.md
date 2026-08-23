# PDF → Livre audio

Web app privée : on dépose un PDF, il est lu à voix haute (voix naturelle) et devient un MP3 écoutable en streaming ou téléchargeable depuis un téléphone.

Prévue pour être auto-hébergée sur un Raspberry Pi 5 (Kali Linux) et accessible via Tailscale — rien n'est exposé sur internet.

## Moteurs de synthèse vocale

Deux moteurs, choisis **par livre** dans le formulaire :

| Moteur | Coût | Qualité | Notes |
|---|---|---|---|
| **Edge TTS** (défaut) | Gratuit, illimité | Très bonnes voix neurales Microsoft (fr-FR-DeniseNeural, HenriNeural…) | API non officielle : peut casser sans prévenir ; pas de clonage vocal |
| **ElevenLabs** | Payant au caractère | Top du marché + clonage de votre voix | Nécessite `ELEVENLABS_API_KEY` |

## Fonctionnement

1. Upload d'un PDF via le navigateur → extraction et nettoyage du texte (en-têtes, numéros de page, césures).
2. **Estimation affichée avant conversion** : gratuit pour Edge TTS, % du quota mensuel pour ElevenLabs.
3. Clic sur « Convertir » → découpe en chunks ≤ 4000 caractères → synthèse → assemblage ffmpeg en un seul MP3. Reprise sans re-facturation si interrompu.
4. Écoute dans le navigateur (reprise de position, vitesse de lecture) ou téléchargement.

## Développement local (Mac)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # inclut pytest et reportlab pour les tests
cp .env.example .env   # remplir ELEVENLABS_API_KEY (optionnel si Edge TTS suffit)
uvicorn app.main:app --reload
# http://localhost:8000
```

Tests :

```bash
pytest
```

L'extraction de texte et la conversion Edge TTS fonctionnent sans clé API ; seule la conversion ElevenLabs consomme des crédits.

## Déploiement sur le Raspberry Pi 5 (Kali Linux)

### 1. Code et dépendances

```bash
# depuis le Mac : rsync -av --exclude .venv --exclude data audio_book/ kali@<ip-du-pi>:~/audiobook/
sudo apt update && sudo apt install -y ffmpeg python3-venv python3-pip
cd ~/audiobook
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID
```

### 2. Service systemd

```bash
# adapter User= et WorkingDirectory= dans audiobook.service si besoin
sudo cp audiobook.service /etc/systemd/system/
sudo systemctl enable --now audiobook
journalctl -u audiobook -f   # logs
```

Le service n'écoute **que sur l'IP Tailscale** de la machine (`--host $(tailscale ip -4)`) : il est injoignable depuis le LAN local, et rien n'est exposé sur internet. Tailscale doit donc être installé et connecté **avant** le démarrage du service (section suivante).

### 3. Tailscale (accès privé depuis le téléphone)

Le script d'install officiel ne détecte pas Kali → installer le dépôt Debian Bookworm à la main :

```bash
curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt update && sudo apt install -y tailscale
sudo tailscale up
```

Sur le téléphone : installer l'app Tailscale, se connecter au même compte (ou inviter le téléphone sur le tailnet via la console admin). Le site est alors joignable à :

```
http://<nom-du-pi>.<tailnet>.ts.net:8000
```

### 4. HTTPS (optionnel)

`tailscale serve` peut exposer le service en HTTPS avec un certificat automatique :

```bash
sudo tailscale serve --bg 8000
# -> https://<nom-du-pi>.<tailnet>.ts.net
```

## Coûts ElevenLabs

| Plan | Prix | Caractères/mois | Équivalent |
|---|---|---|---|
| Free | 0 $ | 10 000 | tester la voix |
| Starter | ~5 $/mois | 100 000 | 1-2 livres courts |
| Creator | ~22 $/mois | 500 000 | un roman de ~300 pages |

L'app affiche l'estimation (caractères + % du quota) avant chaque conversion. Ajuster `MONTHLY_QUOTA_CHARS` dans `.env` selon votre plan. Le texte extrait est conservé : un livre interrompu en cours de mois peut être relancé plus tard sans re-upload.

## Cloner votre voix (étape suivante)

1. Enregistrer 1 à 3 minutes de votre voix (calme, sans bruit de fond, micro correct).
2. Dashboard ElevenLabs → Voices → *Add a new voice* → *Instant Voice Cloning* (inclus dès le plan Starter).
3. Copier l'ID de la voix créée dans `.env` → `ELEVENLABS_VOICE_ID=...`
4. `sudo systemctl restart audiobook`

Aucun changement de code : la voix est un paramètre de configuration.

## Dépannage

- **« PDF scanné, OCR non supporté »** : le PDF est une image. Le passer d'abord dans un OCR (ex. `ocrmypdf in.pdf out.pdf`) puis re-uploader.
- **« Quota ElevenLabs atteint »** : quota mensuel consommé ; attendre le renouvellement, monter de plan, ou rebasculer le livre sur Edge TTS (gratuit). Le livre passe en erreur avec un bouton « Réessayer la conversion » — les segments déjà générés ne seront pas re-facturés.
- **Le site ne répond plus sur le réseau local** : normal, le service n'écoute que sur Tailscale. Vérifier `tailscale status` sur le Pi et sur le téléphone.
- **Voix qui change de langue** : le modèle `eleven_multilingual_v2` suit le paramètre langue choisi à l'upload (fr/en).
- **Logs** : `journalctl -u audiobook -f` sur le Pi ; le texte extrait de chaque livre est dans `data/text/<id>.txt`.
