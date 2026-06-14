db = db.getSiblingDB('nova');

db.createUser({
  user: 'nova_user',
  pwd: 'SFdsfg2345-dsfsa342',
  roles: [
    { role: 'readWrite', db: 'nova' }
  ]
}); 