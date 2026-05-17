// FUN_1406df3c0 @ 0x1406df3c0
// purpose-guess: field_register_helper
// callers (1):
//   FUN_1406cd990 @ 1406cd990


undefined8 * FUN_1406df3c0(void)

{
  undefined8 *puVar1;
  
  LOCK();
  DAT_141415474 = DAT_141415474 + 1;
  UNLOCK();
  puVar1 = (undefined8 *)_malloc_base(0xa8);
  if (puVar1 == (undefined8 *)0x0) {
    puVar1 = (undefined8 *)0x0;
  }
  else {
    FUN_140c97530(puVar1,0,0xa8);
    FUN_1404f63e0(puVar1);
    *puVar1 = oCTMetaAttribute<class_oCEntitySettings>::vftable;
  }
  FUN_140c9673c(puVar1);
  return puVar1;
}

