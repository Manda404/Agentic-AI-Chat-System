# Deploiement Cloud Gratuit

Ce projet se deploie proprement en separant l'application des services manages deja gratuits.

## Architecture recommandee

```text
Frontend Next.js        -> Vercel Hobby
Backend FastAPI Docker -> Render Free
MongoDB Atlas          -> cluster free existant
Redis                  -> Redis Cloud Free existant
LLM                    -> HuggingFace Router
```

## 1. Backend sur Render

Le fichier `render.yaml` cree un Web Service Docker gratuit a partir de `backend/Dockerfile`.

Dans Render:

1. Connecter le repository GitHub.
2. Choisir `New` puis `Blueprint`.
3. Selectionner ce repository.
4. Render detecte `render.yaml`.
5. Remplir les variables marquees `sync: false`.

Variables obligatoires a renseigner:

```env
BACKEND_CORS_ORIGINS=https://ton-frontend.vercel.app
HUGGINGFACE_API_KEY=...
MONGODB_URI=...
REDIS_URL=...
AUTH_SECRET_KEY=...
```

Generation conseillee pour `AUTH_SECRET_KEY`:

```bash
openssl rand -hex 32
```

Apres deployement, verifier:

```text
https://ton-backend.onrender.com/health
```

Limites Render Free importantes:

- le service peut dormir apres une periode sans trafic;
- le redemarrage peut prendre environ une minute;
- le filesystem est ephemere, donc les fichiers uploades dans `backend/data` ne sont pas un stockage durable.

## 2. Frontend sur Vercel

Dans Vercel:

1. Importer le repository GitHub.
2. Choisir `frontend` comme Root Directory.
3. Garder les commandes Next.js par defaut:
   - Build Command: `npm run build`
   - Install Command: `npm install`
   - Output: auto
4. Ajouter la variable:

```env
NEXT_PUBLIC_BACKEND_URL=https://ton-backend.onrender.com
```

Puis redeployer le frontend.

## 3. MongoDB Atlas

Garder MongoDB Atlas en service externe. Ne pas le mettre dans Docker pour le free tier.

Verifier que les index suivants existent dans la collection configuree:

- `documents_search`
- `documents_vector`

La dimension vectorielle doit rester coherente avec `MODEL_EMBEDDING`.
Par defaut, `BAAI/bge-small-en-v1.5` utilise `384` dimensions.

## 4. Redis

Utiliser ton Redis Cloud Free existant, puis mettre son URL dans Render:

```env
REDIS_URL=redis://default:mot_de_passe@host.redis.io:port
```

Si Redis Cloud indique que TLS/SSL est active, utiliser `rediss://` au lieu de `redis://`.

Le backend a un fallback memoire, mais il ne faut pas compter dessus en cloud:

- les comptes utilisateurs peuvent disparaitre au redemarrage;
- les conversations ne sont pas partagees entre instances;
- le cache est perdu.

## 5. Ordre de deploiement

1. Pousser le repo sur GitHub.
2. Verifier MongoDB Atlas et Redis.
3. Deployer le backend Render.
4. Tester `/health`.
5. Deployer le frontend Vercel avec `NEXT_PUBLIC_BACKEND_URL`.
6. Mettre l'URL Vercel dans `BACKEND_CORS_ORIGINS` cote Render.
7. Tester register, login, ingest, upload, chat.

## 6. CI/CD recommande

Le workflow GitHub Actions `.github/workflows/ci.yml` verifie chaque push et pull request vers `main`:

- tests backend Python;
- build frontend Next.js.

Configuration conseillee:

1. Pousser une branche de travail.
2. Ouvrir une pull request vers `main`.
3. Attendre que GitHub Actions soit vert.
4. Merger dans `main`.
5. Vercel redeploie le frontend depuis Git.
6. Render redeploie le backend depuis Git.

Dans Render, regler le backend sur:

```text
Auto-Deploy: After CI Checks Pass
```

Ainsi, Render attend que GitHub Actions reussisse avant de deployer le backend.
Si tu veux deployer plus vite pendant le developpement, tu peux garder:

```text
Auto-Deploy: On Commit
```

Vercel lance aussi ses deployements automatiquement depuis Git. Chaque pull request obtient une preview, puis `main` devient la production.

## Points a ameliorer ensuite

- Stocker les fichiers uploades dans un stockage objet durable: Cloudflare R2, S3, Supabase Storage.
- Ajouter une route d'admin protegee pour verifier les index MongoDB.
- Desactiver les modeles trop lourds si le quota HuggingFace gratuit est limite.
