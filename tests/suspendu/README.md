# Tests en suspens — intégration Google Drive

L'option Google Drive **n'est pas active**. Le code (`app/services/drive.py`) et
ces tests sont conservés intacts pour pouvoir la réactiver sans la réécrire.

Ces tests ne sont **pas** joués par `scripts/run_tests.sh`. Pour les lancer :

```bash
docker exec faithbook-backend rm -rf /app/tests
docker cp tests faithbook-backend:/app/tests
docker exec -w /app/tests/suspendu faithbook-backend python3 test_drive.py
docker exec -w /app/tests/suspendu faithbook-backend python3 test_run_with_drive.py
```

39 vérifications, aucun credential requis (l'API Google est simulée).

Pour réactiver Drive, voir le README principal §2.
