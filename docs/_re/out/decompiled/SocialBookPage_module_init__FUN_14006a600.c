// FUN_14006a600 @ 0x14006a600
// purpose-guess: SocialBookPage_module_init
// callers (0):


void FUN_14006a600(void)

{
  uint uVar1;
  uint uVar2;
  uint uVar3;
  longlong *plVar4;
  uint uVar5;
  
  if (DAT_1414142a7 == '\0') {
    DAT_14140ded0 = FUN_1404f4ef0();
    DAT_14140ded8 = (longlong *)FUN_1404f4ef0();
    DAT_14140dee0 = FUN_1404f4ef0();
    DAT_1414142a7 = '\x01';
  }
  plVar4 = DAT_14140ded8;
  uVar1 = *(uint *)(DAT_14140ded8 + 1);
  uVar2 = *(uint *)((longlong)DAT_14140ded8 + 0xc);
  uVar5 = uVar1 + 1;
  if (uVar2 < uVar5) {
    uVar3 = 8;
    if (8 < uVar2) {
      uVar3 = uVar2;
    }
    for (; uVar3 < uVar5; uVar3 = uVar3 * 2) {
    }
    FUN_140153520(DAT_14140ded8);
  }
  *(uint *)(plVar4 + 1) = uVar5;
  *(code **)(*plVar4 + (ulonglong)uVar1 * 8) = FUN_140405b80;
  DAT_141448b48 = 0;
  return;
}

