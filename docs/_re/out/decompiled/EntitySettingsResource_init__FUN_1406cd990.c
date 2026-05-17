// FUN_1406cd990 @ 0x1406cd990
// purpose-guess: EntitySettingsResource_init
// callers (0):


void FUN_1406cd990(longlong *param_1)

{
  longlong lVar1;
  char *local_18;
  undefined4 local_10;
  
  local_10 = 0x80000016;
  local_18 = "EntitySettingsResource";
  (**(code **)(*param_1 + 0x18))(param_1,&local_18);
  local_10 = 0x8000000b;
  *(undefined4 *)param_1[0x11] = 1;
  local_18 = "m_oSettings";
  lVar1 = FUN_1406df3c0();
  FUN_1404f2360(DAT_141446f38,lVar1,0x16f75a74,&local_18);
  *(undefined8 *)(lVar1 + 0x48) = DAT_141446e38;
  local_18 = "*.entity.ot";
  local_10 = 0x8000000b;
  FUN_14048eef0(param_1,&local_18);
  DAT_141441be8 = 0;
  return;
}

